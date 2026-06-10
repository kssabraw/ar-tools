# PRD: Sources Cited Module

**Version:** 1.1
**Status:** Draft
**Last Updated:** April 30, 2026
**Part of:** ShowUP Local — Content Generation Platform
**Upstream Dependencies:** Content Writer Module (v1.4+) · Research & Citations Module (v1.1+)
**Downstream Dependency:** Content Editor Module

---

## 1. Problem Statement

The Content Writer Module produces a complete blog post with factual claims grounded in verified citations from the Research & Citations Module. In v1.3, the Writer placed inline Markdown hyperlinks at the point of citation use. That approach conflates citation *marking* (which claim, in which sentence) with citation *formatting* (how the source is displayed to the reader) — leaving no clean separation between prose content and reference presentation.

This module introduces that separation. It receives the Writer's article JSON — now containing inline `{{citation_id}}` markers at the exact sentence of use — and the Research Module's verified citation pool. It resolves each marker into a numbered superscript with a jumplink, builds a formatted Sources Cited section in MLA style at the bottom of the article, and outputs a single enriched JSON document ready for the downstream Content Editor Module.

---

## 2. Goals

- Accept the Content Writer Module's structured JSON output (v1.4+, with `{{citation_id}}` inline markers) and the Research & Citations Module's citation pool as independent inputs
- Replace each `{{citation_id}}` marker in prose with a numbered HTML superscript linking to its corresponding entry in the Sources Cited section
- Assign citation numbers sequentially by order of first appearance in the article (top to bottom)
- Produce a formatted Sources Cited section in MLA-derived style (title, publication, URL only — author and date omitted in v1; see Section 7 Step 3 for rationale), containing only citations marked `used: true` by the Writer Module
- Render all external URLs in the Sources Cited section with `rel="nofollow"`
- Output an enriched JSON document that preserves the full Writer Module schema, with marker substitutions applied and a Sources Cited block appended to the article array
- Produce no net changes to prose content — only marker substitution and section addition

### Out of Scope (v1)
- Citation style formats other than the simplified MLA-derived format defined in Section 7 Step 3
- Author names and publication dates in MLA entries (deferred to v2 — see Section 7 Step 3 rationale)
- Inline hyperlinks within prose (handled in Sources Cited section only; prose contains superscripts, not hyperlinks)
- Citations for images, figures, or non-prose content
- Link-rot detection or citation validation post-generation
- User-facing citation management UI
- Footnote-style rendering (bottom-of-page floating notes) — jumplink anchors only
- Citation deduplication across articles or projects
- Multi-locale support — English / United States only
- CMS publishing or schema markup injection

---

## 3. Success Metrics

| Metric | Target |
|---|---|
| Output validates against JSON schema | 100% |
| Every `{{citation_id}}` marker in prose is replaced with a superscript | 100% |
| Every superscript jumplinks correctly to its Sources Cited entry | 100% |
| Sources Cited contains only `used: true` citations from the Writer output | 100% |
| All Sources Cited URLs rendered with `rel="nofollow"` | 100% |
| Citation numbers assigned in order of first appearance | 100% |
| End-to-end generation completes within 15s | ≥95% |
| Cost per article under $0.05 | ≥95% |

---

## 4. Upstream Dependency Changes

This module requires breaking changes to the Content Writer Module. These changes must ship as **Content Writer Module v1.4** before this module can operate.

### 4A — Inline Marker Output (Writer v1.3 → v1.4)

The Writer Module must place a `{{citation_id}}` marker at the exact point in prose where a verified claim is used, immediately following the sentence that contains the citation.

**Marker format:** `{{cit_001}}` — double curly braces wrapping the `citation_id` value, no spaces.

**Citation ID format constraint:** All `citation_id` values produced by the Research Module and consumed here must match the regex `^cit_[0-9]+$` (e.g., `cit_001`, `cit_42`). This constraint is required for safe and unambiguous marker pattern matching. The Research Module PRD should be updated to document this format constraint explicitly.

**Placement rule:** The marker is inserted *after the closing punctuation* of the sentence containing the cited claim.

**Multiple citations in one sentence:** If a single sentence references more than one citation, markers are stacked in the order the claims appear within that sentence: `{{cit_001}}{{cit_004}}`. Note that the rendered superscript order is sorted ascending by assigned citation number — see Step 2.

**Example (Writer v1.4 body output):**
```
Water heaters typically last 8–12 years before requiring replacement.{{cit_003}} The most common failure point is the anode rod, which degrades over time and accelerates tank corrosion.{{cit_007}}
```

**Per-section reconciliation:** The Writer Module continues to populate `citations_referenced` per article section (array of `citation_id` values used in that section's body). This field is used by this module for validation.

### 4B — Removal of Inline Hyperlink Placement (Writer v1.3 → v1.4)

The Writer Module must no longer place Markdown inline hyperlinks (`[anchor text](URL)`) in prose. The Sources Cited Module is the sole citation formatting layer. All citation presentation — numbering, linking, and reference listing — is handled here.

This change affects Step 4F and the Business Rules in the Writer PRD. The `inline_link_placed` field in the Writer's `citation_usage` output block should be deprecated in Writer v1.4 or repurposed to track marker placement.

### 4C — Body Field Format Declaration (Writer v1.4)

The Writer Module v1.4 PRD should explicitly declare its `article[].body` field format as Markdown (specify exact flavor — e.g., GitHub Flavored Markdown / CommonMark) and document that body strings may contain `{{citation_id}}` markers as plain text inline tokens. This locks down the format contract for all downstream consumers.

---

## 5. Inputs

The Sources Cited Module receives two upstream JSON payloads on each run. Both are required. If either is missing or fails schema validation, the module aborts with a structured error.

### Input A — Content Writer Module Output (v1.4+ schema)

The full JSON output from the Content Writer Module. Key fields consumed:

| Field | Usage |
|---|---|
| `keyword` | Cross-validated against Research Module `keyword` |
| `article[]` | Ordered array of article sections; body fields are scanned for `{{citation_id}}` markers |
| `article[].body` | Markdown prose containing `{{citation_id}}` markers at point of citation use |
| `article[].citations_referenced[]` | Array of `citation_id` values used in this section — used to validate all markers are accounted for |
| `article[].order` | Section order index — used to establish first-appearance sequence for citation numbering |
| `article[].type` | Section type — Sources Cited section is appended after the `conclusion` type |
| `citation_usage.usage[]` | Per-citation `used` flag — determines which citations are included in Sources Cited |
| `citation_usage.usage[].citation_id` | Used to resolve which citations from the Research pool appear in Sources Cited |
| `metadata.schema_version` | Validated against expected Writer schema version (1.4+) |

### Input B — Research & Citations Module Output (v1.1+ schema)

The full JSON output from the Research & Citations Module. Key fields consumed:

| Field | Usage |
|---|---|
| `keyword` | Cross-validated against Writer Module `keyword` |
| `citations[]` | Full citation pool — resolved by `citation_id` to retrieve publication metadata for MLA formatting |
| `citations[].citation_id` | Lookup key — matched against markers found in prose; must conform to `^cit_[0-9]+$` |
| `citations[].url` | External URL — rendered with `rel="nofollow"` in Sources Cited |
| `citations[].title` | Source title — used in MLA entry |
| `citations[].publication` | Publication or site name — used in MLA entry |
| `citations[].tier` | Recorded in output metadata; not used in formatting |

Note: `citations[].author` and `citations[].published_date` are **not consumed** in v1. See Section 7 Step 3 rationale.

### Input Cross-Validation

| Check | Failure Behavior |
|---|---|
| `writer.keyword == research.keyword` (case-insensitive) | Abort with structured error if mismatch |
| Writer schema version is 1.4+ | Abort if schema version is below 1.4 — marker output is not present in earlier versions |
| Any `{{citation_id}}` marker found in prose that has no matching entry in `research.citations[]` | Abort with structured error listing unresolvable markers |
| Any `{{citation_id}}` marker found in prose where the `citation_id` does not appear in `citation_usage.usage[]` | Abort with structured error — see Step 1 integrity check rationale |
| Any `citation_id` value encountered that does not match `^cit_[0-9]+$` | Abort with structured error |
| Any `citation_id` in `citation_usage.usage[]` where `used: true` has no corresponding marker in any `article[].body` | Flag `orphaned_usage_record: true` in metadata; do not include in Sources Cited |
| `article[].citations_referenced[]` lists a `citation_id` with no corresponding marker in that section's body | Flag `marker_reconciliation_warning: true` per section; proceed |

---

## 6. System Architecture Overview

```
[Writer JSON (v1.4+)] + [Research & Citations JSON]
              │
              ▼
┌─────────────────────┐
│  Step 0: Input      │  ◄── Schema validation, keyword match, marker
│  Validation         │      resolvability check, ID format check
└─────────────────────┘
              │
              ▼
┌─────────────────────┐
│  Step 1: Marker     │  ◄── Scan all article[].body fields
│  Discovery &        │  ◄── Extract all {{citation_id}} markers in
│  Numbering          │      order of first appearance
└─────────────────────┘
              │
              ▼
┌─────────────────────┐
│  Step 2: Superscript│  ◄── Replace each marker with HTML superscript
│  Injection          │  ◄── Sort stacked markers ascending
│                     │  ◄── Anchor href → Sources Cited entry
└─────────────────────┘
              │
              ▼
┌─────────────────────┐
│  Step 3: MLA        │  ◄── Resolve citation metadata from Research pool
│  Entry Generation   │  ◄── Format each used citation (title + publication + URL)
│                     │  ◄── Apply rel="nofollow" to all URLs
└─────────────────────┘
              │
              ▼
┌─────────────────────┐
│  Step 4: Sources    │  ◄── Build numbered list ordered by citation number
│  Cited Section      │  ◄── Append as final article section (after conclusion)
│  Assembly           │
└─────────────────────┘
              │
              ▼
┌─────────────────────┐
│  Step 5: Output     │  ◄── Assemble enriched JSON
│  Assembly           │  ◄── Preserve full Writer schema
│                     │  ◄── Add sources_cited_metadata block
└─────────────────────┘
              │
              ▼
[Enriched JSON Article → Content Editor Module]
```

---

## 7. Functional Requirements

### Step 0 — Input Validation

All validation runs before any processing begins.

| Rule | Action |
|---|---|
| Either input JSON is missing | Abort with structured error |
| Either input fails schema validation | Abort with structured error |
| `writer.keyword != research.keyword` (case-insensitive) | Abort with structured error |
| Writer schema version below 1.4 | Abort — inline markers not present in earlier versions |
| A `{{citation_id}}` marker in prose has no match in `research.citations[]` | Abort with structured error listing all unresolvable marker values |
| A `{{citation_id}}` marker in prose has a `citation_id` not present in `citation_usage.usage[]` | Abort with structured error — integrity violation between Writer prose and Writer reconciliation record (see Step 1) |
| Any encountered `citation_id` does not match `^cit_[0-9]+$` | Abort with structured error |
| `article[]` is empty | Abort with structured error |

---

### Step 1 — Marker Discovery & Citation Numbering

The module performs a single sequential scan of all `article[].body` fields, in ascending `order` index, to discover all `{{citation_id}}` markers and assign citation numbers.

**Scanning rules:**
- Scan body fields only — heading fields (`article[].heading`) are not scanned for markers and must not contain markers
- Process sections in `order` ascending (matching the article's reading sequence)
- Within a body field, process markers left-to-right as they appear in the text
- Marker pattern: `\{\{(cit_[0-9]+)\}\}` — the captured group is the `citation_id`

**Numbering algorithm:**
- Maintain a `citation_number_map`: a dictionary keyed by `citation_id`, assigned a sequential integer starting at 1
- When a `citation_id` is encountered for the first time: assign the next available number and add to the map
- When a `citation_id` is encountered again in a later section: reuse the existing number — no new entry is created
- Final numbering reflects strict first-appearance order across the full article

**Output of Step 1:**
- `citation_number_map`: `{ "cit_003": 1, "cit_007": 2, "cit_001": 3, ... }`
- `ordered_used_citations`: list of `citation_id` values in citation number order (used for Sources Cited section assembly in Step 4)

**Integrity check (replaces "prose is ground truth" rule from v1.0):**

The Writer Module's marker placement is deterministic post-processing (Python/JS string assembly from a known `citation_id` list), not an LLM operation — hallucinated marker IDs are not the expected risk. However, schema drift, copy-paste errors, or upstream bugs could produce inconsistent state where prose markers and the `citation_usage` reconciliation record disagree.

To catch these defensively:

- Every `citation_id` extracted from prose markers **must** appear in `citation_usage.usage[]`. If not: abort the run with a structured error (see Step 0). This ensures the Writer's prose output and its own reconciliation record are internally consistent before this module proceeds.
- Every `citation_id` in `citation_usage.usage[]` where `used: true` must have at least one corresponding marker found in the scan. If not: flag `orphaned_usage_record: true` in metadata and exclude that citation from Sources Cited (no abort — this is a softer inconsistency that does not corrupt output).

The `unexpected_marker` flag and "prose is ground truth" handling from v1.0 are removed.

---

### Step 2 — Superscript Injection

Each `{{citation_id}}` marker in every `article[].body` field is replaced with an HTML superscript element.

**Substitution format:**

```html
<sup><a href="#sources-cited-{n}" id="ref-{citation_id}-{instance}">[{n}]</a></sup>
```

Where:
- `{n}` = the citation number from `citation_number_map`
- `#sources-cited-{n}` = the anchor ID of the corresponding Sources Cited list entry (see Step 4)
- `{citation_id}` = the raw citation ID (e.g., `cit_003`)
- `{instance}` = an integer representing the nth occurrence of this citation in the article (1-indexed), to give each superscript a unique `id` for back-references if needed (e.g., `ref-cit_003-1`, `ref-cit_003-2`)

**Stacked marker sort rule:**

When two or more markers appear consecutively (with no intervening prose between them), the rendered superscripts must be sorted in **ascending citation number order** — not source-text order.

This produces clean numeric runs like `[3][5]` rather than `[5][3]`, regardless of the order the markers were placed in the source. This matters because citation numbers are assigned by first-appearance across the full article, so a marker pair placed `{{cit_001}}{{cit_004}}` in the source could legitimately render as `[5][3]` if `cit_004` happened to appear earlier in the article. Sorting ascending eliminates that visual oddity.

Sort scope is per stacked group only. Markers separated by any prose character (including whitespace) are not part of the same stack and are not reordered relative to each other.

**Example — single marker:**

Input body text:
```
Water heaters typically last 8–12 years before requiring replacement.{{cit_003}}
```

Output body text:
```
Water heaters typically last 8–12 years before requiring replacement.<sup><a href="#sources-cited-1" id="ref-cit_003-1">[1]</a></sup>
```

**Example — stacked markers (multiple citations on one sentence), assuming `cit_001` was assigned number 5 and `cit_004` was assigned number 3:**

Input:
```
Installation costs vary by region and unit type.{{cit_001}}{{cit_004}}
```

Output (sorted ascending — `[3]` rendered before `[5]`):
```
Installation costs vary by region and unit type.<sup><a href="#sources-cited-3" id="ref-cit_004-1">[3]</a></sup><sup><a href="#sources-cited-5" id="ref-cit_001-1">[5]</a></sup>
```

**Rules:**
- Markers are replaced in-place; no surrounding whitespace is added or removed
- Within a stacked group, source-order is overridden by ascending citation-number order
- No other changes are made to the body text — word choice, punctuation, capitalization, and structure are preserved exactly
- Heading fields (`article[].heading`) are passed through unchanged; markers in heading fields cause an abort (Step 0)

---

### Step 3 — Citation Entry Generation

For each citation in `ordered_used_citations`, generate a formatted entry. v1 uses a simplified MLA-derived format that omits author and publication date entirely.

**v1 format (applied to all entries):**

```
"Title of Page." Publication Name, <a href="URL" rel="nofollow">URL</a>.
```

**Rationale for omitting author and date in v1:**

Strict MLA 9th edition requires author name inversion (`Last, First`) and publication date formatting. Both fields require parsing logic that is fragile against real-world input:

- Author strings arrive in inconsistent formats (already-inverted, organizational, multi-author, with credentials, multi-word last names) and the Research Module does not constrain the format. A naive inverter will silently produce malformed entries (e.g., re-inverting `"Smith, John"` to `"John, Smith"`).
- Publication date strings arrive in unpredictable formats (ISO 8601, partial dates, scraped natural language like "March 15, 2023" or "2 days ago") and the Research Module's schema only declares `published_date: "string | null"` with no format guarantee.

Rather than ship fragile parsing logic in v1 that produces silently incorrect entries, both fields are dropped entirely. Citation entries remain useful (title, publication, URL are sufficient for reader verification) and consistent. Author and date support is deferred to v2, contingent on either (a) upstream format guarantees from the Research Module, or (b) implementation of robust parsers with documented fallback behavior.

**Field resolution rules:**

| Element | Source Field | Fallback |
|---|---|---|
| Title | `citations[].title` | Required — placeholder entry if absent (see Failure Modes) |
| Publication name | `citations[].publication` | If absent: use root domain of `citations[].url` |
| URL | `citations[].url` | Required — placeholder entry if absent (see Failure Modes); rendered with `rel="nofollow"` |

**Title formatting:**
- Web page titles are rendered in quotation marks: `"Title of Page."`
- The period is placed inside the closing quotation mark (standard MLA)

**Publication name formatting:**
- Rendered in italics. In the HTML list body output (Step 4), publication names are wrapped in `<em>` tags.

**URL rendering:**
- The URL is both the hyperlink text and the href: `<a href="https://example.com/page" rel="nofollow">https://example.com/page</a>`
- The trailing period follows the closing `</a>` tag

**Full example:**
```html
"How to Replace a Water Heater Anode Rod." <em>This Old House</em>, <a href="https://www.thisoldhouse.com/plumbing/anode-rod" rel="nofollow">https://www.thisoldhouse.com/plumbing/anode-rod</a>.
```

**Publication-as-domain example (publication field absent):**
```html
"Water Heater Energy Efficiency Standards." <em>energy.gov</em>, <a href="https://www.energy.gov/energysaver/water-heaters" rel="nofollow">https://www.energy.gov/energysaver/water-heaters</a>.
```

**LLM usage:** Citation entry generation is fully deterministic — no LLM call is required or used. All formatting is handled by template logic from structured citation metadata.

---

### Step 4 — Sources Cited Section Assembly

The Sources Cited section is built as a numbered list, ordered by citation number (ascending), and appended to the article as the final section.

**Section structure:**

The Sources Cited section is represented as two entries appended to `article[]`:

1. **Header entry** (`type: "sources-cited-header"`, `level: "H2"`, `heading: "Sources Cited"`)
2. **Body entry** (`type: "sources-cited-body"`, `level: "none"`) — contains the full numbered list as an HTML ordered list

**HTML list format:**

```html
<ol class="sources-cited">
  <li id="sources-cited-1">"How to Replace a Water Heater Anode Rod." <em>This Old House</em>, <a href="https://www.thisoldhouse.com/plumbing/anode-rod" rel="nofollow">https://www.thisoldhouse.com/plumbing/anode-rod</a>.</li>
  <li id="sources-cited-2">...</li>
</ol>
```

**Anchor ID convention:** Each `<li>` carries `id="sources-cited-{n}"`, where `{n}` is the citation number. This is the target of the superscript jumplinks injected in Step 2.

**Order:** Entries appear in citation number order (order of first appearance in article prose). This is the `ordered_used_citations` list from Step 1.

**Section ordering:** The Sources Cited header is assigned `order: <conclusion_order + 1>`; the body entry is assigned `order: <conclusion_order + 2>`, where `conclusion_order` is the `order` value of the existing conclusion section in the Writer's article array. These are appended after the conclusion section.

---

### Step 5 — Output Assembly

The output is the full Content Writer Module JSON schema passed through intact, with the following modifications:

1. All `article[].body` fields have had `{{citation_id}}` markers replaced with superscript HTML (Step 2)
2. Two new entries appended to `article[]`: the Sources Cited header and body (Step 4)
3. A new top-level `sources_cited_metadata` block added (see Output Schema)
4. `metadata.schema_version` updated to reflect Sources Cited Module processing

No other fields from the Writer Module output are modified or removed.

**Output format contract — downstream consumers must preserve:**

The output `article[].body` fields are **Markdown with embedded HTML**. Downstream consumers (Content Editor Module and any subsequent renderers) must preserve the following without stripping or modification:

| Element | Reason |
|---|---|
| `<sup>` tags | Citation superscript display |
| `<a>` tags | Citation jumplinks and external citation links |
| `<ol>` and `<li>` tags | Sources Cited list structure |
| `<em>` tags | Publication name italics |
| `id` attributes on `<a>` and `<li>` | Required for jumplink targeting |
| `href` attributes on `<a>` | Required for both internal jumplinks (`#sources-cited-N`) and external citation URLs |
| `rel="nofollow"` attribute on external `<a>` tags | SEO requirement — must not be stripped |
| `class="sources-cited"` on `<ol>` | Used for downstream styling and identification |

Any HTML sanitizer in the downstream pipeline must be configured to allow these tags and attributes. Markdown renderers must be configured to permit raw HTML pass-through (GitHub Flavored Markdown and CommonMark do this by default). End-to-end rendering testing is required before this module ships — see Section 13.

---

## 8. Output Schema

The output schema extends the Content Writer Module v1.4 output schema. Only additions and modifications are documented here — all existing Writer fields pass through unchanged.

```json
{
  "keyword": "string",
  "intent_type": "string",
  "title": "string",

  "article": [
    {
      "order": 0,
      "level": "H1 | H2 | H3 | none",
      "type": "content | faq-header | faq-question | conclusion | sources-cited-header | sources-cited-body | h1-enrichment",
      "heading": "string | null",
      "body": "string ({{citation_id}} markers replaced with superscript HTML)",
      "word_count": 0,
      "section_budget": 0,
      "citations_referenced": ["cit_001"]
    },
    {
      "order": "<conclusion_order + 1>",
      "level": "H2",
      "type": "sources-cited-header",
      "heading": "Sources Cited",
      "body": null,
      "word_count": null,
      "section_budget": null,
      "citations_referenced": []
    },
    {
      "order": "<conclusion_order + 2>",
      "level": "none",
      "type": "sources-cited-body",
      "heading": null,
      "body": "<ol class=\"sources-cited\">...</ol>",
      "word_count": null,
      "section_budget": null,
      "citations_referenced": []
    }
  ],

  "citation_usage": {
    "...": "passed through from Writer output unchanged"
  },

  "sources_cited_metadata": {
    "total_citations_in_sources_cited": 0,
    "citation_number_map": {
      "cit_003": 1,
      "cit_007": 2,
      "cit_001": 3
    },
    "orphaned_usage_records": [],
    "marker_reconciliation_warnings": [],
    "entries_with_missing_publication": ["cit_007"],
    "entries_with_placeholder": [],
    "schema_version": "1.0",
    "writer_schema_version": "1.4",
    "generation_time_ms": 0
  },

  "format_compliance": {
    "...": "passed through from Writer output unchanged"
  },

  "metadata": {
    "...": "all existing Writer metadata fields passed through unchanged",
    "sources_cited_module_version": "1.0"
  }
}
```

---

## 9. Failure Mode Handling

| Scenario | Behavior |
|---|---|
| Either input JSON missing or fails schema validation | Abort with structured error |
| Writer schema version below 1.4 | Abort — markers not present; instruct caller to upgrade Writer Module |
| `writer.keyword != research.keyword` | Abort with structured error |
| Unresolvable `{{citation_id}}` marker (no match in `research.citations[]`) | Abort with structured error listing all unresolvable IDs |
| `{{citation_id}}` marker in prose with `citation_id` not present in `citation_usage.usage[]` | Abort with structured error — Writer integrity violation |
| `citation_id` value does not match `^cit_[0-9]+$` | Abort with structured error |
| Marker found in a heading field (`article[].heading`) | Abort — headings must not contain citation markers |
| Citation in `citation_usage.usage[]` where `used: true` but no marker found in prose | Flag `orphaned_usage_record: true`; exclude from Sources Cited; do not abort |
| `citations[].title` absent for a used citation | Generate placeholder entry: `[Citation data unavailable — manual review required]`; flag in `entries_with_placeholder`; do not abort |
| `citations[].url` absent for a used citation | Same as missing title — placeholder entry, flagged |
| `citations[].publication` absent | Use root domain of `citations[].url` as publication; flag in `entries_with_missing_publication`; do not abort |
| `article[]` is empty | Abort with structured error |
| End-to-end generation exceeds 15s | Abort with structured timeout error |

---

## 10. Performance Targets

This module performs no LLM calls. All processing is deterministic template logic and string operations.

| Stage | Target | Max |
|---|---|---|
| End-to-end | 3s | 15s |
| Input validation | <1s | 2s |
| Marker discovery & numbering (full article scan) | <1s | 2s |
| Superscript injection (all body fields) | <1s | 2s |
| Citation entry generation (per citation, in-memory) | <1s | 2s |
| Sources Cited assembly & output packaging | <1s | 2s |

Performance is bounded by article length and citation count, not by external API calls. Articles with 20+ citations and 3,000+ word bodies are expected to complete well within the 3s target.

---

## 11. Cost Model

| Component | Cost per Article |
|---|---|
| LLM calls | $0.00 — none required |
| External API calls | $0.00 — none required |
| Compute (string processing, template rendering) | Negligible |
| **Estimated total per article** | **~$0.00** |
| **Budget ceiling** | **$0.05** |

This module adds no meaningful marginal cost to the pipeline. The per-article budget ceiling of $0.05 is a safety buffer for infrastructure overhead only.

**Combined pipeline cost (all modules):**
Adding this module does not change the previously documented combined estimate of **$0.63–$1.24** per article.

---

## 12. Business Rules Summary

| Rule | Value |
|---|---|
| Locale | English / United States |
| Citation style | MLA-derived simplified format (title + publication + URL only); author and date omitted in v1 |
| Citations included in Sources Cited | `used: true` citations only (from Writer `citation_usage`) — orphaned records excluded |
| Ground truth for citation inclusion | Writer `citation_usage` record; markers in prose must be consistent with the record (mismatches abort) |
| Citation ID format constraint | `^cit_[0-9]+$` — enforced; non-conforming IDs abort the run |
| Citation numbering | Sequential integers starting at 1, by order of first appearance in article prose |
| Repeated citation in multiple sections | Same citation number reused; appears once in Sources Cited |
| Superscript format | `<sup><a href="#sources-cited-{n}">[{n}]</a></sup>` |
| Stacked citations (multiple on one sentence) | Rendered superscripts sorted ascending by citation number, regardless of source-text marker order |
| Sources Cited section heading | "Sources Cited" (exact text, H2 level) |
| Sources Cited section position | After conclusion; final section in article |
| External URL link attribute | `rel="nofollow"` on all URLs in Sources Cited |
| Inline hyperlinks in prose | None — superscript numbers only |
| Heading fields | Must not contain markers; markers in headings cause abort |
| Prose content modification | None — only marker substitution; no word changes |
| Author in citation entries | Omitted in v1 |
| Publication date in citation entries | Omitted in v1 |
| Missing publication in citation metadata | Substitute root domain of URL; flag |
| Missing title or URL | Placeholder entry; flag; do not abort full run |
| Output body field format | Markdown with embedded HTML |
| LLM calls | None |
| Schema version required (Writer) | 1.4+ |

---

## 13. What This PRD Does Not Cover

To be addressed in the engineering implementation spec:

- HTML sanitization rules and configuration for the Content Editor Module and any downstream renderer to ensure required tags/attributes (see Step 5) are preserved
- End-to-end rendering pipeline testing — before this module ships, render a sample article through the full pipeline to the final published HTML and verify: jumplinks function, `rel="nofollow"` survives to final HTML, superscripts display correctly, and `id` attributes are preserved
- Markdown renderer configuration — confirm the chosen renderer (likely GitHub Flavored Markdown / CommonMark) permits raw HTML pass-through and does not strip the required tags/attributes
- Handling of malformed markers (e.g., `{{cit_001}` — mismatched braces, partial matches) — current marker regex `\{\{(cit_[0-9]+)\}\}` will not match these; engineering should decide whether to silently leave them as literal text or abort
- Output storage schema in Supabase
- Authentication and API key management
- Logging and observability (marker counts, field coverage rates, generation timing)
- Schema versioning compatibility with future Writer and Research Module schema versions
- Content Editor Module input schema requirements — may require further output format adjustments
- Back-reference links from Sources Cited entries pointing back to each superscript in prose (bidirectional jumplinks) — deferred to v2
- Author and publication date support in citation entries — deferred to v2 pending upstream format guarantees or robust parser implementation

---

## 14. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-29 | Initial draft |
| 1.1 | 2026-04-30 | Inverted marker integrity rule — Writer `citation_usage` record is now authoritative; markers in prose without matching `usage` records abort the run (was: "prose is ground truth"). Stacked superscripts now sort ascending by citation number. Replaced hardcoded `99`/`100` order values with `<conclusion_order + 1>` and `<conclusion_order + 2>`. Removed author and publication date from citation entries entirely (deferred to v2 pending upstream format guarantees) — eliminates fragile parsing of inconsistent author/date formats. Added `^cit_[0-9]+$` format constraint on `citation_id` and explicit marker regex. Added Section 5 output format contract listing required HTML tags/attributes downstream consumers must preserve. Added Writer v1.4 PRD task (Section 4C) to declare body field format. Removed unmeasurable "MLA structural validation ≥95%" success metric. |
