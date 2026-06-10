# 📄 Product Requirements Document (PRD)

## Product Name
SERP Intelligence Engine (SIE) — Term & Entity Analysis Module

## Subtitle
SERP-Driven Keyword, Entity, and Usage Recommendation Engine

---

# 1. 🎯 Objective

Build the term and entity analysis layer of a larger blog content generation SaaS. This module analyzes top SERP results for a target keyword, extracts competitor content patterns, filters noise, and produces a unified list of scored keyword and entity recommendations with usage guidance.

This module should:

1. Accept a target keyword and location.
2. Pull top SERP results using DataForSEO.
3. Classify SERP result types to determine content eligibility.
4. Scrape eligible ranking pages.
5. Extract content by page zone.
6. Filter noise from scraped content.
7. Lemmatize and generate n-grams (unigrams through quadgrams).
8. Aggregate terms across pages with subsumption and coverage gating.
9. Filter terms by TF-IDF distinctiveness.
10. Filter terms by semantic similarity using embeddings.
11. Extract and categorize entities using Google Natural Language API.
12. Score all terms and entities for relevance.
13. Generate per-zone usage recommendations with configurable outlier handling.
14. Recommend target content length.

This module does NOT generate content briefs, heading structures, FAQ recommendations, intent classifications, or draft scoring. Those are handled by a separate downstream module.

---

# 2. 🧱 System Context

This module is an internal component of a larger SaaS platform that generates blog posts for service-area businesses. It is not a standalone product or API. Its output feeds directly into downstream modules (content brief generation, heading optimization, content writing) within the same system.

The module runs as a series of modular pipeline stages within the platform backend.

---

# 3. 💥 Core Value Proposition

This module replaces the keyword and entity analysis functionality found in tools like SurferSEO, Clearscope, and Page Optimizer Pro with a transparent, customizable pipeline.

The module provides:

- SERP-driven keyword extraction and scoring
- Zone-based n-gram analysis (title, H1, H2, H3, paragraphs)
- Lemmatized term aggregation with n-gram subsumption
- Coverage threshold gating to eliminate noise
- TF-IDF distinctiveness scoring (both as filter and scoring signal)
- Embedding-based semantic filtering
- Entity extraction grounded in Google Natural Language API
- Quadgram zone-weighting for intent-specific phrase detection
- Configurable aggressive/safe outlier handling for usage recommendations
- Percentile-based content length recommendations
- All recommendations classified as Required or Avoid — no ambiguous tiers

---

# 4. 🧱 System Architecture

## High-Level Flow

Keyword Input
↓
Cache Check (return cached result if <7 days old and force_refresh is false)
↓
SERP Data Collection
↓
SERP URL Classification + Near-Duplicate Detection
↓
Content-Eligible URL Filtering
↓
Page Scraping
↓
Content Parsing / Zone Extraction
↓
Noise Filtering
↓
┌──────────────────────────────────────────────────────────┐
│ PARALLEL TRACK A              PARALLEL TRACK B           │
│                                                          │
│ N-Gram Analysis               Entity Extraction          │
│ ↓                             (Google NLP + LLM)         │
│ Term Aggregation                                         │
│ ↓                                                        │
│ Coverage Threshold Gating     Word Count Analysis        │
│ ↓                                                        │
│ TF-IDF Pre-Filter                                        │
│ ↓                                                        │
│ Semantic Filtering                                       │
└───────────────────────┬──────────────────────────────────┘
                        ↓
              Entity–Term Merge
                        ↓
           Recommendation Scoring Engine
                        ↓
           Usage Recommendation Engine
                        ↓
              Store Results to Supabase

---

# 5. 🧩 Core Modules

### Execution Order and Parallelism

Modules 1–6 execute sequentially — each depends on the output of the previous module. After Module 6 (Noise Filtering), the pipeline forks into two parallel tracks:

**Track A (N-Gram Pipeline):** Modules 7 → 8 → 9 → 10. These process the cleaned text into scored, filtered terms.

**Track B (Entity + Word Count):** Modules 11 and 12 run in parallel with Track A. Entity extraction calls the Google NLP API per page and runs the LLM dedup pass. Word count analysis computes percentile ranges from page lengths. Neither depends on n-gram output.

**Merge point:** After both tracks complete, the entity–term merge combines their outputs into a unified term list. This feeds into Module 13 (Scoring) and Module 14 (Usage Recommendations), which execute sequentially.

Parallelizing Track A and Track B significantly reduces total pipeline runtime because the Google NLP API calls in Module 11 are the second most time-consuming operation after scraping.

---

## Module 1: Keyword Input

### Purpose

Accept the primary keyword and configuration inputs needed to run the analysis.

### Input

```json
{
  "keyword": "water heater repair",
  "location_code": 2840,
  "language_code": "en",
  "device": "desktop",
  "depth": 20,
  "outlier_mode": "safe",
  "force_refresh": false
}
```

### Requirements

- Must accept one target keyword per run.
- Must support DataForSEO location codes.
- Must support language code configuration.
- Must support desktop or mobile SERP configuration.
- Must support configurable SERP depth, with a default of top 20 results.
- Must accept `outlier_mode` parameter: `"safe"` (default) or `"aggressive"`.
- Must accept `force_refresh` parameter: `false` (default) or `true`. When `false`, the pipeline checks for cached results for this keyword + location within the last 7 days and returns cached output if available. When `true`, the pipeline runs a fresh analysis regardless of cache state.

---

## Module 2: SERP Collection

### Purpose

Collect top organic SERP results for the target keyword.

### Input

```json
{
  "keyword": "target keyword",
  "location_code": 2840,
  "language_code": "en"
}
```

### Output

```json
{
  "urls": [],
  "titles": [],
  "descriptions": [],
  "ranks": []
}
```

### Requirements

- Use DataForSEO API.
- Collect top 20 organic results by default.
- Preserve ranking position.
- Preserve page title.
- Preserve meta description when available.
- Preserve displayed URL.
- Preserve result type when available.
- Must support retries and error handling.
- Must handle empty or partial SERP responses.

---

## Module 3: SERP URL Classification

### Purpose

Classify each SERP result so the system can decide which pages should be scraped for content extraction.

### Page Categories

Each SERP result should be classified as one of the following:

- Direct competitor
- Informational article
- Local service page
- Product/service landing page
- Directory
- Forum / UGC
- Marketplace
- Government / educational
- Video result
- News result
- Social media result
- Irrelevant result

### Output

```json
{
  "url": "https://example.com",
  "rank": 1,
  "title": "Example Title",
  "page_category": "local service page",
  "content_eligible": true,
  "reason": "The page appears to be a local service page directly relevant to the target keyword."
}
```

### Requirements

- Use only content-eligible pages for n-gram, entity, and usage extraction.
- Exclude or downweight directories, forums, marketplaces, and UGC pages from content usage recommendations unless explicitly allowed.
- Flag irrelevant results.
- Preserve excluded URLs with exclusion reasons.

### Near-Duplicate Page Detection

After scraping, detect and deduplicate pages that serve the same content under different URLs (www vs non-www, HTTP vs HTTPS, mobile subdomains, syndicated content, or mirror pages). Duplicate pages inflate every frequency count, coverage number, and percentile calculation in the pipeline.

**Detection method:** Compare the first 500 characters of cleaned body text (post-noise-filtering) between all pairs of content-eligible pages. If two pages share >90% character-level similarity in this window, flag the lower-ranked page as a duplicate of the higher-ranked page.

**Behavior:**

- The higher-ranked page is retained as the canonical version.
- The lower-ranked duplicate is excluded from all downstream analysis.
- The duplicate is logged with the canonical URL it was matched to.

```json
{
  "url": "https://www.example.com/water-heater-repair",
  "duplicate_of": "https://example.com/water-heater-repair",
  "similarity": 0.96,
  "excluded": true,
  "exclusion_reason": "Near-duplicate of higher-ranked page"
}
```

**Requirements:**

- Must compare body text similarity after scraping and noise filtering.
- Must use the first 500 characters of cleaned body text for comparison.
- Must flag pages with >90% similarity as duplicates.
- Must retain the higher-ranked page and exclude the lower-ranked duplicate.
- Must log all duplicate detections with similarity score.

### Example Exclusion Reasons

- Directory result
- Forum / UGC result
- Marketplace page
- Video result
- Not directly related to keyword
- Thin content
- Blocked from scraping
- Duplicate result
- Non-English page
- Location mismatch

---

## Module 4: Page Scraping

### Purpose

Scrape content from content-eligible SERP URLs.

### Input

```json
{
  "url": "https://example.com"
}
```

### Output

```json
{
  "url": "https://example.com",
  "html": "...",
  "text": "...",
  "markdown": "...",
  "scrape_status": "success"
}
```

### Requirements

- Use ScrapeOwl or equivalent.
- Must handle JavaScript-rendered pages.
- Must handle timeouts.
- Must support retries.
- Must return scrape status.
- Must return failure reason when scraping fails.
- Must skip pages that cannot be scraped after retry limit.
- Must preserve URL association throughout the pipeline.

### Failure Reasons

- Timeout
- Blocked by robots or firewall
- Empty page
- Non-HTML response
- Redirect loop
- JavaScript rendering failure
- HTTP error
- Scrape API error

---

## Module 5: Zone Extraction

### Purpose

Extract content from meaningful page zones for analysis.

### Output Structure

```json
{
  "url": "https://example.com",
  "zones": {
    "title": "Example Title",
    "meta_description": "Example meta description",
    "h1": [],
    "h2": [],
    "h3": [],
    "h4": [],
    "paragraphs": "",
    "lists": [],
    "tables": [],
    "faq_blocks": []
  },
  "word_count": 1400
}
```

### Requirements

- Strip scripts and styles.
- Normalize whitespace.
- Extract title tag.
- Extract meta description when available.
- Extract H1, H2, H3, and optionally H4 headings.
- Extract paragraph body content.
- Extract list items.
- Extract table text when useful.
- Filter low-quality paragraphs under 5 words.
- Preserve zone-level text for later analysis.
- Preserve page-level word count.

---

## Module 6: Noise Filtering

### Purpose

Remove content that would distort recommendations. Uses a five-layer approach applied in order so that each layer catches what the previous one missed.

### Layer 1: Structural HTML Stripping

Before any text analysis, remove elements by HTML tag, class/ID pattern, and ARIA role.

**Remove by tag:** `<nav>`, `<footer>`, `<header>`, `<aside>`, `<noscript>`

**Remove by class/ID pattern match:** Any element with a class or ID containing `sidebar`, `widget`, `menu`, `nav`, `footer`, `breadcrumb`, `cookie`, `banner`, `social-share`, `related-posts`, `author-bio`, `comments`, `newsletter`, `signup`, `cta`

**Remove by ARIA role:** `navigation`, `banner`, `contentinfo`, `complementary`

This layer catches 60–70% of boilerplate on well-structured sites, less on WordPress page builder sites with generic class names.

### Layer 2: Content Extraction by Text Density

Apply content extraction heuristics to isolate the main body content from chrome. For each block-level element, compute:

- `text_density = text_length / total_element_length`
- `link_ratio = link_word_count / total_word_count`

**Rules:**

- Blocks with `link_ratio > 0.3` are classified as navigation and excluded.
- Blocks with fewer than 20 words surrounded by high-link-density blocks are classified as UI chrome and excluded.
- If the scraping service returns a `markdown` or `text` field that has already been extracted from the main content area, evaluate whether that output is clean enough to use directly before applying manual extraction.

### Layer 3: Cross-Page Fingerprinting

This is the most important layer for this use case. It exploits the fact that the pipeline scrapes 10–20 pages per keyword from different domains.

**Process:**

1. After zone extraction, take every paragraph and list item from every scraped page.
2. Normalize each block: lowercase, strip extra whitespace, remove punctuation.
3. Hash or use the normalized string as a key.
4. Count how many unique domains each normalized block appears on.
5. Any block appearing on 3+ different domains is flagged as cross-page boilerplate and excluded from n-gram analysis.

**Granularity:** Apply at both paragraph level (catches large boilerplate blocks) and sentence level (catches boilerplate sentences embedded in otherwise legitimate paragraphs).

**This layer is particularly effective for local service pages**, which share templates and stock phrases like "Licensed, bonded, and insured", "Call us for a free estimate", and "We serve [city] and surrounding areas."

### Layer 4: Heuristic Text Filters

Apply pattern-based filters to remaining text blocks after structural extraction:

- Paragraphs under 5 words: discard.
- Paragraphs that are entirely a phone number, email address, or physical address pattern: exclude from n-gram analysis but preserve for entity extraction (addresses are legitimate local entities).
- Paragraphs where more than 50% of words are proper nouns or city names: likely a service area list, exclude.
- Text blocks matching common CTA patterns ("call now", "get a free", "schedule your", "request a quote"): exclude.

### Layer 5: Post-Extraction Frequency Anomaly Detection

After n-gram analysis in Module 7, apply a final safety net at the term level.

Flag any term where the coefficient of variation in per-page frequency is near zero. If a term like "licensed bonded insured" appears exactly the same number of times on every page, it is template content, not organic usage. Organically used terms will have variable frequency across pages.

**Threshold:** If the coefficient of variation for a term's per-page frequency is below `0.1` and the term appears on 4+ pages, flag it as suspected template boilerplate and exclude from scoring.

### Requirements

- Must apply all five layers in order before n-gram analysis (Layers 1–4) and after n-gram analysis (Layer 5).
- Must preserve meaningful content from the main page body.
- Must avoid removing legitimate service content.
- Must log all removed content with the layer that removed it for debugging.
- Must preserve content removed by Layer 4 (contact info, addresses) for entity extraction even though it is excluded from n-gram analysis.
- Cross-page fingerprinting (Layer 3) is mandatory for MVP.

---

## Module 7: N-Gram Analysis

### Purpose

Generate term candidates from extracted page content by zone.

### Output

```json
{
  "url": "https://example.com",
  "zone_analysis": {
    "h2": {
      "bigrams": {
        "water heater": 2
      },
      "trigrams": {
        "water heater repair": 1
      }
    }
  }
}
```

### Requirements

- Generate:
  - Unigrams
  - Bigrams
  - Trigrams
  - Quadgrams
- **Stopword handling:** Remove stopwords from unigrams only. Preserve stopwords within bigrams, trigrams, and quadgrams so that phrases like "how to repair" and "what is a" remain intact as multi-word candidates.
- Remove punctuation.
- Normalize casing.
- **Lemmatize before counting.** Apply lemmatization (e.g., "repairs" → "repair", "repairing" → "repair", "repaired" → "repair") before n-gram generation. All inflected forms of a word must be collapsed to a single base form so that frequency counts, coverage thresholds, and usage recommendations reflect the true topical signal, not surface-level variation. Lemmatization must be applied consistently across all zones and all pages before any aggregation occurs.
- Track counts per zone.
- Track counts per URL.
- Track total page count.
- Preserve source URL for each n-gram occurrence.
- Avoid overcounting repeated boilerplate terms.
- **Quadgram Zone Weighting:** Quadgrams (4-word phrases) must be flagged when they appear in high-importance zones (title, H1, H2) across 2 or more pages. These are strong signals of intent-specific terminology and must be preserved through all downstream filtering stages regardless of raw frequency. Assign quadgrams a zone multiplier of 1.5x when found in title, H1, or H2 zones during aggregation and scoring.

### Zones to Analyze

- Title
- Meta description
- H1
- H2
- H3
- Paragraphs
- Lists
- Tables
- FAQ blocks

---

## Module 8: Term Aggregation

### Purpose

Combine n-gram data across all analyzed pages.

### Output

```json
{
  "term": "water heater repair",
  "total_count": 12,
  "pages_found": 6,
  "source_urls": [],
  "zones": {
    "h2": {
      "total_count": 5,
      "pages_found": 4
    },
    "paragraphs": {
      "total_count": 7,
      "pages_found": 6
    }
  }
}
```

### Requirements

- Combine terms across all pages.
- Track total count.
- Track pages_found using unique URLs.
- Track source URLs.
- Track zone-level counts.
- Track zone-level pages_found.
- Must aggregate across all items in a single pass.
- Must deduplicate by normalized, lemmatized term.
- Must preserve raw and normalized versions of terms when useful.

### N-Gram Subsumption Rules

After aggregation and before coverage gating, apply subsumption to merge shorter n-grams that are fully contained within a passing longer n-gram.

**Rule:** If a shorter n-gram (e.g., "water heater") is a full substring of a longer n-gram that also passes aggregation (e.g., "water heater repair cost"), the shorter n-gram is merged into the longer one. The longer n-gram inherits the combined frequency counts and zone data from both.

**Merge behavior:**

- The longer n-gram becomes the canonical term in all downstream modules.
- The shorter n-gram is removed from the active candidate list.
- The shorter n-gram is preserved in a `subsumed_by` reference on the longer term for traceability.
- If the shorter n-gram appears on pages where the longer n-gram does not, it is NOT subsumed — it remains independent because it represents distinct usage.
- Subsumption only applies when every occurrence of the shorter n-gram co-occurs with the longer n-gram on the same pages.
- **Sub-phrases of the target keyword must never be subsumed by the target keyword itself.** They may have independent usage patterns across competitor pages and must go through the normal pipeline.

**Output additions:**

```json
{
  "term": "water heater repair cost",
  "n_gram_length": 4,
  "subsumed_terms": ["water heater repair", "heater repair cost"],
  "subsumed_terms_count": 2
}
```

**Requirements:**

- Must apply subsumption after aggregation but before coverage gating.
- Must only subsume when shorter n-gram usage is fully contained within longer n-gram pages.
- Must preserve `subsumed_terms` array on the canonical term for traceability.
- Must not subsume if shorter n-gram has independent page coverage.
- Must not subsume across different zones (e.g., a bigram in H2 is not subsumed by a quadgram that only appears in paragraphs).
- Must not subsume sub-phrases of the target keyword.

### Coverage Threshold Gate

After subsumption, apply a minimum coverage threshold before any term proceeds to TF-IDF or semantic filtering. This prevents rare, single-source terms from consuming embedding budget and polluting recommendations.

**Default rule:** A term must appear on at least 3 of the top 10 content-eligible pages to proceed. Terms below this threshold are moved to a `low_coverage_candidates` pool and excluded from scoring unless manually overridden.

**Exceptions — always allow through regardless of coverage:**

- Quadgrams found in title, H1, or H2 on 2+ pages (intent-specific phrases)
- Terms found exclusively on pages ranked 1–3, provided those pages are from 2+ unique domains (top-of-SERP signal from independent sources)
- Terms flagged by the entity extraction module as high-confidence entities

**Output additions:**

```json
{
  "term": "tankless water heater installation",
  "pages_found": 2,
  "passes_coverage_threshold": false,
  "coverage_exception": "quadgram found in H2 on rank-1 and rank-2 pages",
  "low_coverage_candidate": false
}
```

**Requirements:**

- Must apply coverage gate before TF-IDF and embedding modules.
- Must expose threshold as a configurable parameter (default: 3 of top 10).
- Must log all terms that fail coverage threshold with reason.
- Must preserve `low_coverage_candidates` pool for optional manual review.
- Must not silently discard terms — exclusion reasons must always be recorded.

---

## Module 9: TF-IDF Pre-Filter

### Purpose

Score candidate terms by their distinctiveness within the SERP corpus before passing them to the embedding model. This reduces embedding API cost, removes terms that are common across the web but not distinctive to this SERP, and surfaces phrases that are meaningfully concentrated in the ranking pages.

The TF-IDF score also serves as a scoring input in Module 13 (Recommendation Scoring Engine), not just as a binary gate.

### How It Works

Treat each scraped page as a document and the full set of scraped pages as the corpus. Apply standard TF-IDF:

- **TF (Term Frequency):** How often the term appears in a given page, normalized by page word count.
- **IDF (Inverse Document Frequency):** How rare the term is across all scraped pages. Terms that appear on every page receive low IDF. Terms concentrated on fewer pages receive higher IDF.
- **TF-IDF Score:** TF × IDF. High scores indicate terms that are both frequent on some pages and distinctive relative to the rest of the corpus.

```text
tf(term, page) = term_count_in_page / page_word_count
idf(term, corpus) = log(total_pages / pages_containing_term)
tfidf(term, page) = tf * idf
```

Aggregate per-page TF-IDF scores across all pages to produce a corpus-level TF-IDF signal per term:

```text
corpus_tfidf(term) = average tfidf score across all pages where term appears
```

### Output

```json
{
  "term": "tankless water heater repair cost",
  "corpus_tfidf_score": 0.043,
  "passes_tfidf_threshold": true,
  "tfidf_rank_in_corpus": 12
}
```

### Default Thresholds

- Terms with corpus TF-IDF score below `0.005` are filtered out before embedding.
- Always preserve terms that passed a coverage exception in Module 8, regardless of TF-IDF score.
- Always preserve terms appearing in title, H1, or H2 on 2+ pages, regardless of TF-IDF score.
- Threshold must be configurable.

### Requirements

- Must compute TF-IDF using only content-eligible scraped pages.
- Must normalize term frequency per page word count.
- Must use log-scale IDF.
- Must aggregate per-page scores to a corpus-level signal.
- Must rank all candidate terms by corpus TF-IDF score.
- Must output TF-IDF score and pass/fail status per term.
- Must apply threshold filter before embedding module.
- Must preserve TF-IDF score for use as a scoring input in Module 13.
- Must preserve terms with coverage exceptions or zone-based protections.
- Must expose threshold as a configurable parameter.
- Must log filtered terms with their TF-IDF score for debugging.
- Must batch remaining candidates before passing to embedding module to reduce API calls.

---

## Module 10: Semantic Filtering with Embeddings

### Purpose

Filter extracted terms by semantic relevance to the target keyword.

### Requirements

- Use OpenAI embeddings.
- Recommended model: `text-embedding-3-small`.
- Embed the target keyword.
- Embed each candidate term.
- Compute cosine similarity between term and keyword.
- Default semantic similarity threshold: `0.65`.

### Output

```json
{
  "term": "water heater repair",
  "semantic_similarity": 0.72,
  "passes_semantic_filter": true
}
```

### Dynamic Threshold Logic

The default threshold should be `0.65`, but the system should adjust when needed:

- If fewer than 25 terms pass, lower threshold to `0.60`.
- If more than 300 terms pass, raise threshold to `0.70`.
- Always preserve terms found in title, H1, or H2 across 3+ pages unless clearly irrelevant.
- Always allow manual override of threshold.

### Requirements

- Must filter obviously unrelated terms.
- Must not rely only on raw frequency.
- Must preserve high-value heading terms even if similarity is slightly below threshold.
- Must output semantic similarity score.
- Must output pass/fail status.
- Must output reason when a term is preserved despite threshold.

---

## Module 11: Entity Extraction

### Purpose

Extract meaningful entities from ranking pages and categorize them for use downstream. Uses a two-pass pipeline: Google Natural Language API for grounded NER extraction, followed by an LLM pass for categorization, deduplication, and context enrichment.

### Two-Pass Pipeline

#### Pass 1: Google Natural Language API (NER)

Use the Google Cloud Natural Language API `analyzeEntities` endpoint to extract entities directly from each scraped page's text content. This grounds all entities in actual competitor text — the NLP model cannot invent entities, only surface what is present in the content.

**API call per page:**

```json
{
  "document": {
    "type": "PLAIN_TEXT",
    "content": "<page_body_text>"
  },
  "encodingType": "UTF8"
}
```

**Retain entities meeting all of the following criteria:**

- `salience` score ≥ `0.40`
- Entity type is one of: `PERSON`, `LOCATION`, `ORGANIZATION`, `EVENT`, `WORK_OF_ART`, `CONSUMER_GOOD`, `OTHER`
- Not a navigational artifact (e.g., domain names, menu labels, button text)

**Per-page entity output:**

```json
{
  "url": "https://example.com",
  "ner_entities": [
    {
      "name": "tankless water heater",
      "type": "CONSUMER_GOOD",
      "salience": 0.54,
      "mentions": 5
    }
  ]
}
```

**Requirements:**

- Must call Google NLP API per content-eligible page.
- Must use cleaned body text (post-noise-filtering) as input, not raw HTML.
- Must cap input text at 100,000 bytes per API call (Google NLP limit).
- Must handle API errors with retry logic.
- Must preserve salience score and entity type from API response.
- Must preserve mention count per page.
- Must log pages where NLP API call failed.

#### Pass 2: LLM Categorization and Deduplication

After aggregating NER results across all pages, pass the raw entity list to an LLM for:

1. **Deduplication:** Merge variants of the same entity (e.g., "tankless heater", "tankless water heater", "on-demand water heater").
2. **Categorization:** Map each entity to the standardized category list below.
3. **Context enrichment:** Generate a short example context statement based on how the entity was used across pages.
4. **Relevance filtering:** Flag and exclude entities that are off-topic, purely navigational, or brand-specific with no SEO value.

**The LLM may not invent new entities. It may only process, label, and merge entities returned by the Google NLP API.**

**LLM prompt constraint:**

```text
You will receive a list of entities extracted from competitor pages by Google NLP. 
Your job is to deduplicate, categorize, and filter this list. 
Do not add any entity that is not in the provided list. 
Only output entities that are present in the input.
```

### Output

```json
{
  "entities": [
    {
      "entity": "tankless water heater",
      "category": "equipment",
      "pages_found": 8,
      "avg_salience": 0.51,
      "source_urls": [],
      "example_context": "Mentioned in sections about repair, replacement, and installation.",
      "recommendation_score": 0.81,
      "confidence": "high",
      "ner_variants": ["tankless heater", "on-demand water heater", "tankless water heater"]
    }
  ]
}
```

### Entity–Term Merge

After entity extraction, entities are merged into the unified term list rather than maintained as a separate output. This gives downstream modules a single list of Required terms to work with.

**Merge rules:**

1. **Entity matches an existing term:** If an entity phrase matches a term already in the list from Module 7 (e.g., "tankless water heater" exists as both a trigram and an entity), the existing term entry is enriched with entity fields: `"is_entity": true`, `"entity_category"`, `"avg_salience"`, and `"ner_variants"`. The term's recommendation score receives a `1.15x` multiplier on its final recommendation score because dual-signal terms (both high-frequency n-gram and high-salience entity) are stronger indicators of topical importance.

2. **Entity does not match any existing term:** If an entity has no matching n-gram (e.g., a brand name like "Bradford White" that was mentioned once per page and didn't survive n-gram coverage gating), it is added to the term list as a new entry with `"source": "entity_only"` and `"is_entity": true`. It still goes through recommendation scoring in Module 13 like any other term.

**Match logic:** An entity matches a term if the lemmatized entity name exactly equals the lemmatized term, or if the entity name is a variant listed in `ner_variants` that matches a term.

**Merged term output example:**

```json
{
  "term": "tankless water heater",
  "is_entity": true,
  "entity_category": "equipment",
  "avg_salience": 0.51,
  "ner_variants": ["tankless heater", "on-demand water heater"],
  "source": "ngram_and_entity",
  "total_count": 14,
  "pages_found": 8,
  "recommendation_score": 0.88,
  "recommendation_category": "required",
  "confidence": "high"
}
```

**Entity-only term output example:**

```json
{
  "term": "Bradford White",
  "is_entity": true,
  "entity_category": "brand",
  "avg_salience": 0.44,
  "ner_variants": ["Bradford White"],
  "source": "entity_only",
  "total_count": 4,
  "pages_found": 4,
  "recommendation_score": 0.62,
  "recommendation_category": "required",
  "confidence": "medium"
}
```

**Requirements:**

- Must merge entities into the term list after Module 11 and before Module 13 scoring.
- Must enrich matching terms with entity metadata rather than creating duplicates.
- Must add non-matching entities as new entries with `"source": "entity_only"`.
- Must apply a `1.15x` scoring multiplier to dual-signal terms (`"source": "ngram_and_entity"`) in Module 13.
- Must preserve `ner_variants` on all entity-sourced terms for traceability.
- The final output must contain a single unified `terms` list — no separate `entities` array.

### Entity Categories

- Services
- Products
- Tools
- Equipment
- Brands
- Locations
- People
- Organizations
- Regulations
- Concepts
- Problems
- Symptoms
- Materials
- Methods
- Comparisons
- Pricing factors

### Requirements

- Must use Google Natural Language API as the primary extraction source (Pass 1).
- Must use cleaned, noise-filtered page text as NLP API input.
- Must apply a salience threshold of `0.40` consistently — no two-tier approach.
- Must aggregate NER results across all content-eligible pages before LLM pass.
- Must deduplicate cross-page entity variants in the LLM pass.
- Must include `avg_salience` score in final output.
- Must include `ner_variants` array to show merged forms.
- The LLM may categorize and deduplicate but may not invent entities not returned by Google NLP.
- Each entity must include: entity name, category, pages found, avg salience, source URLs, example context, recommendation score, confidence level, and NER variants.
- Must deduplicate similar entities.
- Must exclude irrelevant brand names unless useful.
- Must exclude unrelated navigation/footer entities.
- Must preserve local entities when relevant to local SEO.
- Must flag pages where NLP API failed so entity coverage can be noted in warnings.

---

## Module 12: Word Count Analysis

### Purpose

Recommend a target content length based on ranking content.

### Output

```json
{
  "recommended_word_count": {
    "min": 1200,
    "target": 1500,
    "max": 1800
  }
}
```

### Requirements

- Use percentile-based calculation:
  - p25 = minimum recommendation
  - p50 = target recommendation
  - p75 = maximum recommendation
- Filter out pages with fewer than 800 words.
- Filter out pages with more than 5000 words.
- Allow configurable min/max filters.
- Exclude directories, forums, and non-content pages.
- Must preserve analyzed word counts for debugging.
- Must flag when too few valid pages are available.

---

## Module 13: Recommendation Scoring Engine

### Purpose

Score all items in the unified term list (n-gram terms, entities, and merged entries) based on usefulness for content creation.

This module separates raw competitor data from actionable recommendations.

### Inputs

- Semantic similarity score
- TF-IDF distinctiveness score (from Module 9)
- Pages found
- Total count
- Zone distribution
- Rank position of source pages
- Presence in title
- Presence in H1
- Presence in H2
- Presence in H3
- Presence in paragraphs
- Entity category
- Page category
- Boilerplate likelihood
- Entity signal (`is_entity`, `avg_salience`, `source` — dual-signal terms receive a scoring boost)

### Output

```json
{
  "term": "water heater repair cost",
  "recommendation_score": 0.84,
  "recommendation_category": "required",
  "recommendation_type": "primary_supporting_term",
  "confidence": "high",
  "reason": "Appears across 7 ranking pages, commonly in H2s, semantically close to target keyword."
}
```

### Recommendation Categories

All items in the unified term list (n-gram terms, entity-only terms, merged entries, and quadgrams) that pass the full filtering pipeline (coverage gate → TF-IDF → semantic filtering → scoring) are classified as **Required**. There is no Recommended / Optional tier. If a term survives the pipeline, it belongs in the content.

The only exception is the **Avoid** classification, which is applied to terms identified as boilerplate, brand-specific noise, or overoptimized outliers that should explicitly not be used.

- Required
- Avoid

### Target Keyword Handling

The primary target keyword (e.g., "water heater repair") must always appear in the output as a Required term with the following minimum usage rules, regardless of competitor analysis:

- **Title:** At least 1 occurrence
- **H1:** At least 1 occurrence
- **Paragraphs:** At least 1 occurrence

The target keyword is exempt from coverage gating, TF-IDF filtering, and semantic filtering. It is inserted directly into the Required terms list with a fixed recommendation score of `1.00` and confidence `"high"`.

**Minimum usage floor:** The minimum usage values above (1 in title, 1 in H1, 1 in paragraphs) act as a floor. When Module 14 computes percentile-based usage ranges from competitor data, the final recommendation for the target keyword uses the *higher* of the two minimums per zone. For example, if Module 14 computes a paragraph range of min: 4 / target: 6 / max: 8, the target keyword's paragraph minimum becomes 4 (not 1). If Module 14 computes a paragraph range of min: 0 / target: 1 / max: 2, the target keyword's paragraph minimum stays at 1 (the floor).

Sub-phrases of the target keyword (e.g., "water heater" and "heater repair" from "water heater repair") must go through the normal pipeline. They are not automatically included or excluded — they are treated as any other bigram candidate. However, they must not be subsumed by the target keyword itself during n-gram subsumption (Module 8), since they may have independent usage patterns across competitor pages.

```json
{
  "term": "water heater repair",
  "is_target_keyword": true,
  "recommendation_score": 1.00,
  "recommendation_category": "required",
  "confidence": "high",
  "minimum_usage": {
    "title": 1,
    "h1": 1,
    "paragraphs": 1
  }
}
```

### Recommendation Types

- Primary supporting term
- Secondary supporting term
- Entity candidate
- Overused/noisy term
- Boilerplate term
- Brand-specific term
- Location-specific term

### Scoring Requirements

- Prioritize terms found across multiple unique URLs.
- Boost terms found in important zones.
- Boost terms from higher-ranking pages.
- Boost terms that appear in headings across multiple pages.
- Penalize terms appearing on only one page.
- Penalize boilerplate/navigation terms.
- Penalize weak semantic matches.
- Penalize brand-specific terms unless relevant.
- Penalize terms from excluded page categories.
- Penalize suspiciously high usage from one overoptimized page.

### Scoring Weights

```json
{
  "semantic_similarity_weight": 0.25,
  "tfidf_distinctiveness_weight": 0.10,
  "pages_found_weight": 0.25,
  "zone_importance_weight": 0.20,
  "rank_weight": 0.10,
  "intent_alignment_weight": 0.10
}
```

### Input Normalization

Before applying weights, all scoring inputs must be normalized to a 0–1 scale using min-max normalization across the candidate set:

```text
normalized_value = (value - min_value) / (max_value - min_value)
```

This prevents inputs with different natural scales from dominating the score. For example, `semantic_similarity` naturally ranges 0.0–1.0 while `pages_found` could range 1–10. Without normalization, `pages_found` would overpower other signals at higher weights.

Apply min-max normalization independently per input across all candidate terms in the current run. If all candidates share the same value for an input (e.g., all have `pages_found = 5`), set the normalized value to `0.5` for that input to avoid division by zero.

**Note on intent alignment:** Without a dedicated intent classification module, intent alignment is inferred from the page category distribution in Module 3. If the majority of content-eligible pages are local service pages, terms found predominantly on local service pages receive a higher intent alignment score than terms found only on informational articles.

### Quadgram Zone-Weighting

Quadgrams (4-word phrases) receive a zone multiplier applied on top of the base `zone_importance_weight` when they appear in high-signal zones. This reflects the fact that 4-word phrases in titles and headings almost always represent deliberate, intent-specific terminology rather than incidental co-occurrence.

**Multiplier rules:**

- Quadgram found in title or H1 on 2+ pages: apply `1.5x` zone importance multiplier
- Quadgram found in H2 on 2+ pages: apply `1.4x` zone importance multiplier
- Quadgram found in H3 on 2+ pages: apply `1.2x` zone importance multiplier
- Quadgram found only in paragraphs: no multiplier (standard scoring)

**Additional quadgram scoring rules:**

- Quadgrams that passed the coverage threshold via exception (Module 8) must still receive the zone multiplier if found in title/H1/H2.
- Quadgrams must be flagged in their recommendation output with `"n_gram_length": 4` and `"zone_boost_applied": true` so downstream modules understand why a lower-frequency phrase is ranked highly.
- Quadgrams must never be penalized for low raw frequency if they qualify for zone boost.

**Updated output example:**

```json
{
  "term": "emergency water heater repair service",
  "n_gram_length": 4,
  "recommendation_score": 0.79,
  "zone_boost_applied": true,
  "zone_boost_reason": "Found in H2 on 4 ranking pages",
  "recommendation_category": "required",
  "recommendation_type": "primary_supporting_term",
  "confidence": "high",
  "reason": "4-word phrase appearing in H2 across 4 ranking pages. Zone multiplier applied (1.4x). Strong intent-specific topical signal."
}
```

### Confidence Levels

Every recommendation must include a confidence level:

- High
- Medium
- Low

### Confidence Rules

High confidence usually requires:

- Found across multiple ranking pages
- Semantically relevant
- Appears in meaningful content zones
- Not likely boilerplate

Medium confidence usually means:

- Relevant but less common
- Strong semantic match but lower page coverage
- Found in useful zones but not widely repeated

Low confidence usually means:

- Weak page coverage
- Lower semantic similarity
- Possible boilerplate
- Appears mainly on one page

---

## Module 14: Usage Recommendation Engine

### Purpose

Generate recommended usage ranges for important terms by content zone.

### Output

```json
{
  "term": "emergency plumber",
  "mode": "safe",
  "usage": {
    "title": "0–1",
    "h1": "0–1",
    "h2": "1–2",
    "h3": "0–2",
    "paragraphs": "2–5"
  },
  "confidence": "high",
  "warning": null
}
```

### Requirements

- Use percentile-based ranges.
- Normalize term frequency per 1000 words.
- Separate recommendations by zone:
  - Title
  - Meta description
  - H1
  - H2
  - H3
  - Paragraphs
- Must not recommend keyword stuffing.
- Must interpret usage ranges as guidance, not strict requirements.
- Must include confidence levels.
- Must include warnings when a recommendation may be noisy or overoptimized.

### Frequency Formula

For each page and term:

```text
term_frequency_per_1000_words = term_count / word_count * 1000
```

Across eligible pages:

```text
min = p25 frequency
target = p50 frequency
max = p75 frequency
```

Convert frequency back into recommended usage based on target article word count:

```text
recommended_count = frequency_per_1000_words * target_word_count / 1000
```

### Example Output

```json
{
  "term": "water heater repair",
  "paragraph_usage": {
    "min": 2,
    "target": 4,
    "max": 6
  }
}
```

### Outlier Mode: Aggressive vs. Safe

The system must support two outlier-handling modes, selectable per run. This controls how single-page frequency outliers affect percentile calculations.

#### Safe Mode (default)

Before computing percentile ranges, detect single-page outliers per term. If one page uses a term at 3x or more the median frequency of all other pages, exclude that page's frequency from the percentile calculation for that term.

**Example:** If 9 pages use "emergency water heater repair" 1–3 times, but one page uses it 18 times, Safe Mode excludes the outlier page. The p25/p50/p75 range is computed from the remaining 9 pages only.

```json
{
  "term": "emergency water heater repair",
  "mode": "safe",
  "outlier_pages_excluded": 1,
  "outlier_page_url": "https://spammy-competitor.com",
  "outlier_frequency": 18,
  "corpus_median_frequency": 2.3,
  "usage": {
    "paragraphs": {
      "min": 1,
      "target": 2,
      "max": 3
    }
  }
}
```

#### Aggressive Mode

Include all pages in the percentile calculation, including outliers. This benchmarks against the most-used competitor pages, which may produce higher usage recommendations. Useful when the user wants to match or exceed the most aggressive competitors.

```json
{
  "term": "emergency water heater repair",
  "mode": "aggressive",
  "outlier_pages_excluded": 0,
  "usage": {
    "paragraphs": {
      "min": 2,
      "target": 4,
      "max": 8
    }
  },
  "warning": "Aggressive mode includes competitor outlier pages. High-end recommendations may reflect keyword stuffing patterns."
}
```

**Requirements:**

- Must support `"mode": "safe"` (default) and `"mode": "aggressive"` as a run-level configuration.
- Safe Mode must detect outliers using a 3x median threshold per term per zone.
- Safe Mode must exclude outlier pages only for the specific term where the outlier occurs — the page is not globally excluded.
- Safe Mode must log excluded outlier pages with their URL and frequency.
- Aggressive Mode must include all pages and add a warning when p75 exceeds 2x the p50.
- Mode must be selectable at runtime via a configuration parameter.
- Both modes must still apply the over-optimization cap: if the recommended max usage exceeds 10 occurrences per 1,000 words for any single term, flag it regardless of mode.

---

# 6. 📊 Data Model

## Final Output Model

```json
{
  "schema_version": "1.0",
  "keyword": "",
  "location_code": "",
  "language_code": "",
  "outlier_mode": "safe",
  "cached": false,
  "cache_date": null,
  "run_date": "",
  "serp_summary": {
    "analyzed_urls": [],
    "excluded_urls": [],
    "failed_urls": [],
    "dominant_page_type": ""
  },
  "word_count": {
    "min": 0,
    "target": 0,
    "max": 0,
    "source_word_counts": []
  },
  "terms": {
    "required": [],
    "avoid": [],
    "low_coverage_candidates": []
  },
  "term_signals": {
    "coverage_threshold_applied": true,
    "tfidf_threshold_applied": true,
    "terms_filtered_by_coverage": 0,
    "terms_filtered_by_tfidf": 0,
    "terms_passed_to_embedding": 0,
    "subsumption_merges": 0
  },
  "usage_recommendations": [],
  "target_keyword": {
    "term": "",
    "is_target_keyword": true,
    "recommendation_score": 1.00,
    "minimum_usage": {
      "title": 1,
      "h1": 1,
      "paragraphs": 1
    }
  },
  "warnings": []
}
```

## Output Storage

Analysis results are persisted to Supabase for caching and downstream consumption.

**Table:** `keyword_analyses` (or equivalent — schema to be defined during implementation)

**Storage requirements:**

- Must store the complete output JSON per keyword + location run.
- Must store a `run_date` timestamp.
- Must support lookup by keyword + location to enable 7-day cache checks.
- Must support `force_refresh` override that bypasses cache and writes a new row.
- Must not delete previous runs when a fresh analysis is triggered — historical results are preserved.
- Schema design is deferred to implementation. The PRD defines the JSON output shape (above); the Supabase table structure should store it efficiently but does not need to decompose every nested field into separate columns.

---

# 7. ⚙️ Functional Requirements

## Must Have

- Keyword input with outlier mode selection
- DataForSEO SERP collection
- SERP URL classification
- Content-eligible URL filtering
- ScrapeOwl page scraping
- Zone-based content extraction
- Noise filtering
- Lemmatized n-gram analysis (unigrams through quadgrams)
- N-gram subsumption
- Term aggregation
- Coverage threshold gating
- TF-IDF pre-filtering (as gate and scoring input)
- Google Natural Language API entity extraction (NER, salience ≥ 0.40)
- LLM entity categorization and deduplication
- Embedding-based semantic filtering
- Percentile-based word count recommendations
- Percentile-based usage recommendations with aggressive/safe mode
- Recommendation scoring with TF-IDF and quadgram zone-weighting
- Target keyword auto-inclusion with minimum usage rules
- Required / Avoid classification (no ambiguous tiers)
- Confidence levels on all recommendations
- Five-layer noise filtering (structural, text density, cross-page fingerprinting, heuristic, frequency anomaly)
- Entity–term merge into unified term list
- 7-day result caching with force-refresh option
- Minimum page threshold (5 pages) with degraded-confidence continuation
- Modular pipeline architecture
- Error handling
- Rate-limit handling

## Should Have

- Rank-weighted recommendations
- Excluded URL reporting
- Scrape failure reporting
- Dynamic semantic threshold logic
- Outlier page logging in safe mode

## Nice to Have

- Batch keyword processing
- Historical tracking and re-analysis
- Configurable lemmatizer selection
- Custom stopword lists

---

# 8. 🚨 Constraints

## Platform Constraints

- Must integrate as an internal module within the larger SaaS platform.
- Must be callable by upstream orchestration (API endpoint, task queue, or direct function call).
- Must return structured JSON output consumable by downstream modules.

## API Constraints

- Must handle DataForSEO API limits.
- Must handle ScrapeOwl API limits.
- Must handle OpenAI API rate limits.
- Must handle Google Natural Language API rate limits and 100,000 byte input cap.
- Must handle concurrent Google NLP API requests with rate limiting (the `analyzeEntities` endpoint processes one document per request — there is no batch endpoint).
- Must support retries.
- Must support rate-limit backoff between burst requests.
- Must support failed item recovery.

## Processing Constraints

- Must avoid processing too many n-grams unnecessarily.
- Must apply coverage gating and TF-IDF filtering before embeddings to reduce API cost.
- Must batch embedding requests when possible.
- Must deduplicate and lemmatize terms before embeddings.
- Must cap candidate terms before semantic filtering when needed.
- Must avoid LLM calls on raw noisy content.
- Must preserve enough debugging data to inspect failures.

---

# 9. 🛡️ Guardrails

## Keyword Stuffing Guardrails

The system must not recommend keyword stuffing.

Usage ranges should be framed as:

- Natural inclusion guidance
- SERP pattern guidance
- Topical coverage signals

Not as:

- Exact quotas
- Required repetition counts
- Density targets

Both aggressive and safe modes must apply the hard cap of 10 occurrences per 1,000 words per term.

## False Precision Guardrails

The system must avoid making weak recommendations sound exact.

Every major recommendation should include:

- Confidence level
- Reason
- Supporting page coverage
- Warning when confidence is low

## LLM Hallucination Guardrails

The LLM must not invent:

- Entities
- Competitor patterns
- Statistics
- SERP claims

All entity recommendations must be grounded in Google NLP API output from scraped SERP data. The LLM may only categorize, deduplicate, and filter — never invent.

## Minimum Page Threshold

The pipeline requires a minimum of **5 content-eligible, successfully scraped pages** to proceed. If fewer than 5 pages are available after URL classification and scraping, the pipeline continues but attaches a prominent warning to the output:

```json
{
  "warning_level": "critical",
  "warning": "Only N content-eligible pages were available. Recommendations may be unreliable due to insufficient sample size.",
  "pages_available": N
}
```

The pipeline must never abort silently. It always produces output, even with degraded confidence.

## Noisy SERP Guardrails

The system must flag:

- Too few eligible pages (fewer than 5 content-eligible pages — see above)
- Too many failed scrapes (more than 30% failure rate)
- Directory-heavy SERPs
- Forum-heavy SERPs
- Outlier word counts
- Overoptimized competitor pages
- Heavy boilerplate contamination

---

# 10. 📈 Success Metrics

## Module Quality Metrics

- Successful scrape rate
- Failed scrape rate
- Average processing time per keyword
- API cost per keyword (DataForSEO + ScrapeOwl + Google NLP + OpenAI embeddings)
- Number of usable Required terms per run
- Percentage of low-confidence recommendations
- Percentage of hallucination-free entity outputs
- Coverage gate pass-through rate
- TF-IDF filter pass-through rate
- Semantic filter pass-through rate
- Average number of entities extracted per keyword
- Subsumption merge rate

## Downstream Impact Metrics (measured by consuming modules)

- Percentage of generated pages ranking in top 10
- Organic traffic growth for optimized pages
- Content gap reduction vs. SERP competitors
- Coverage of SERP topics in generated content

---

# 11. 🧪 MVP Scope

## MVP Should Include

1. Keyword input with outlier mode and force-refresh option
2. DataForSEO SERP collection
3. SERP URL classification
4. ScrapeOwl scraping
5. Zone extraction
6. Five-layer noise filtering (all layers including cross-page fingerprinting)
7. Lemmatized n-gram generation (stopwords removed from unigrams only)
8. N-gram subsumption
9. Term aggregation
10. Coverage threshold gating
11. TF-IDF pre-filtering (as gate and scoring input)
12. Embedding-based semantic filtering
13. Google NLP API entity extraction (salience ≥ 0.40)
14. LLM entity categorization and deduplication
15. Entity–term merge into unified term list
16. Word count recommendation
17. Recommendation scoring (with min-max normalization, TF-IDF input, quadgram zone-weighting)
18. Target keyword auto-inclusion
19. Usage recommendations with aggressive/safe mode
20. Minimum page threshold (5) with degraded-confidence continuation
21. 7-day Supabase result caching with force-refresh
22. Supabase output storage

## MVP Can Exclude

- Batch keyword processing
- Historical trend tracking across multiple runs
- Configurable lemmatizer selection
- Custom stopword lists

---

# 12. 🏁 Summary

The SERP Intelligence Engine — Term & Entity Analysis Module is the keyword and entity extraction layer of a larger blog content generation SaaS. It combines:

- SurferSEO-style keyword usage analysis
- Clearscope-style semantic relevance filtering
- Google NLP-grounded entity extraction merged into a unified term list
- TF-IDF distinctiveness scoring (as both filter and scoring signal)
- Quadgram zone-weighting for intent-specific phrase detection
- Lemmatized n-gram subsumption to eliminate redundancy
- Coverage threshold gating to eliminate noise
- Configurable aggressive/safe outlier handling

The key design principle is:

Raw SERP data should not automatically become editorial guidance.

Instead, the system must lemmatize, subsume, gate by coverage, filter by distinctiveness, filter by semantic relevance, score by multi-signal weighting, and validate — all before a term earns Required status.

Every term in the output survived a five-stage pipeline. That is the product.
