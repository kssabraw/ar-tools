# Content Writer Module — v1.5 Change Specification

**Document Type:** Delta / Change Specification
**Base Version:** Writer Module PRD v1.4
**Target Version:** Writer Module PRD v1.5
**Date:** April 30, 2026
**Last Revised:** April 30, 2026 (decisions resolved on caching strategy and banned-term detection)
**Status:** Draft — Ready for Implementation
**Driven By:** Platform PRD v1.2 (introduces per-client brand context)

---

## Decisions Resolved

The following design decisions were settled during PRD review and are reflected throughout this document:

| # | Decision | Rationale |
|---|---|---|
| D1 | **Brand voice card is regenerated per run, not cached on the client record.** Each run executes Step 3.5a fresh against the current `brand_guide_text` and `icp_text` from the platform's `client_context_snapshots` table. The resulting card is persisted to Supabase as part of the run's `module_outputs` record (via the `brand_voice_card_used` output field). | Simplest correct behavior. Aligns with the platform's snapshot model — past runs always reflect the brand voice card produced from the brand guide that existed at run time. No cache invalidation logic needed when brand guides are edited. |
| D3 | **Brand always wins in all conflict scenarios.** Brand-banned terms are excluded even when SIE marks them Required. Brand-preferred terms are used even when SIE marks them Avoid. There is no scenario where SIE overrides brand preference. | The team's content is produced for specific clients with defined brand identities. SIE's term recommendations are SERP-derived intelligence, not client mandates. Brand compliance is the non-negotiable constraint; SERP optimization is the goal within that constraint. |
| D4 | **Brand guide and ICP are provided as JSON or Markdown.** The platform preserves the original format on storage and passes it to the Writer's distillation step in its native format. PDF/DOCX uploads are converted to extracted text. The distillation LLM handles both JSON and Markdown inputs. | Structured JSON brand guides allow more precise term extraction. Markdown preserves intended hierarchy and emphasis. Neither format is flattened to plain text unnecessarily. |
| D5 | **Website analysis provides factual reference data only — services, locations, and contact info.** Tone and positioning signals are NOT extracted from the website. All tone and voice signals come exclusively from `brand_guide_text` and `icp_text`. | Cleaner separation of concerns. The website scrape is factual ground truth; brand identity is the client's own declared voice, not what the scraper infers from homepage copy. | The Writer constructs a case-insensitive, word-boundary regex from `brand_voice_card.banned_terms` and runs it against all generated content (sections, headings, FAQs, intro, conclusion). | Deterministic, fast, cheap, debuggable. LLM-based contextual detection (catching paraphrases of banned phrases) is a v1.6 candidate if regex misses prove problematic in practice. |

---

## Summary of Changes

Writer v1.5 introduces a fourth input — `client_context` — and the logic to apply per-client brand voice, audience targeting, and website-derived signals to generated content. The module gains two preprocessing steps that run before section writing, and one new output block.

| Change | Type | Scope |
|---|---|---|
| Add Input D: `client_context` | Schema addition | Input contract |
| Add Step 3.5a: Brand Voice Distillation | New preprocessing step | Pipeline |
| Add Step 3.5b: Brand–SIE Term Reconciliation | New preprocessing step | Pipeline |
| Modify Step 4 (Section Writing): inject brand voice card + filtered SIE terms | Behavioral change | Pipeline |
| Modify Step 5 (FAQ Writing): inject ICP context | Behavioral change | Pipeline |
| Modify Step 6 (Intro/Conclusion Writing): inject brand voice card + positioning | Behavioral change | Pipeline |
| Add output block: `brand_conflict_log[]` | Schema addition | Output contract |
| Add output block: `brand_voice_card_used` | Schema addition | Output contract |
| Update business rules for brand precedence | Rule change | Section 11 |
| Update failure modes for client context handling | Rule addition | Section 12 |
| Bump output `schema_version` to `1.5` | Schema metadata | Output contract |

The Brief, Research & Citations, and SIE input schemas (Inputs A, B, C) are **unchanged** in v1.5.

---

## 1. New Input D: Client Context

### 1.1 Input D Schema

A new top-level input is added alongside Inputs A, B, C:

```json
{
  "client_context": {
    "brand_guide_text": "string (raw text, may be up to 100,000 characters)",
    "icp_text": "string (raw text, may be up to 100,000 characters)",
    "website_analysis": {
      "services": ["string"],
      "locations": ["string"],
      "tone": ["string (3–5 adjectives)"],
      "positioning": "string (≤50 words)"
    },
    "website_analysis_unavailable": false
  }
}
```

### 1.2 Field Semantics

| Field | Required | Notes |
|---|---|---|
| `brand_guide_text` | Yes | Content in original format — JSON or Markdown preferred; plain text for PDF/DOCX uploads. Max 150,000 characters. The distillation LLM (Step 3.5a) handles both JSON and Markdown natively. |
| `icp_text` | Yes | Same format rules as `brand_guide_text`. Max 150,000 characters. |
| `website_analysis` | Conditional | Required when `website_analysis_unavailable` is `false`. Must be omitted or `null` when unavailable is `true`. |
| `website_analysis.services` | Yes | Possibly empty list. |
| `website_analysis.locations` | Yes | Possibly empty list. |
| `website_analysis.tone` | Yes | List of 3–5 tone adjectives extracted from website. |
| `website_analysis.positioning` | Yes | Single sentence ≤50 words. |
| `website_analysis_unavailable` | Yes | Boolean flag; when `true`, module proceeds with brand_guide_text + icp_text only and skips all website-derived prompt enrichment. |

### 1.3 Backward Compatibility

If `client_context` is **omitted entirely** from a request payload, the module falls back to v1.4 behavior — no brand voice card, no reconciliation, no `brand_conflict_log`. This preserves backward compatibility for direct module testing without needing to construct synthetic client context. The `schema_version` in the output is reported as `1.5-no-context` to make this fallback explicit in logs.

When `client_context` is present, v1.5 behavior is mandatory and complete.

---

## 2. New Step 3.5a: Brand Voice Distillation

### 2.1 Purpose

Compress `brand_guide_text` (up to 100,000 chars) and `icp_text` (up to 100,000 chars) into a compact, prompt-ready "brand voice card" that is injected verbatim into every section-writing, FAQ-writing, and intro/conclusion prompt downstream. This avoids re-injecting the full raw text into every section call.

### 2.2 Execution Order

Runs in parallel with Step 3.5b after Inputs A, B, C, D are validated. Both 3.5a and 3.5b must complete before Step 4 (Section Writing) begins.

### 2.3 LLM Call

Single LLM call (model: same as section writing). Input: `brand_guide_text` + `icp_text` + `website_analysis` (if available). Output: structured JSON conforming to the schema below.

### 2.4 Output Schema (Brand Voice Card)

```json
{
  "brand_voice_card": {
    "tone_adjectives": ["string"],
    "voice_directives": ["string (max 200 chars each, max 8 items)"],
    "audience_summary": "string (≤300 chars)",
    "audience_pain_points": ["string (max 5 items)"],
    "audience_goals": ["string (max 5 items)"],
    "preferred_terms": ["string (max 20 items)"],
    "banned_terms": ["string (max 30 items)"],
    "discouraged_terms": ["string (max 20 items)"],
    "client_services": ["string (max 15 items, from website_analysis.services)"],
    "client_locations": ["string (max 15 items, from website_analysis.locations)"],
    "client_contact_info": {
      "phone": "string or null",
      "email": "string or null",
      "address": "string or null",
      "hours": "string or null"
    }
  }
}
```

### 2.5 Distillation Rules

The distillation prompt must handle both JSON and Markdown inputs:

- **If `brand_guide_text` is valid JSON:** parse structure to extract tone adjectives, banned/discouraged/preferred terms, and any explicit audience or style directives from named fields. The LLM uses the JSON structure to locate guidance precisely.
- **If `brand_guide_text` is Markdown:** extract the same signals from prose and formatted sections, treating headers as category indicators (e.g., a section headed "Banned Terms" maps to `banned_terms`).
- **If `brand_guide_text` is plain text (PDF/DOCX upload):** same approach as Markdown — extract signals from prose.

The distillation prompt must:

- Extract tone adjectives from `brand_guide_text` exclusively. **Do not supplement from `website_analysis`** — website analysis provides factual reference data only (services, locations, contact info), not tone signals.
- Extract banned, discouraged, and preferred terms from `brand_guide_text`. A term is `banned` only when the brand guide explicitly prohibits it. A term is `discouraged` when the brand guide expresses preference against it without explicit prohibition. A term is `preferred` when the brand guide names it as preferred phrasing.
- Summarize the ICP from `icp_text` into a single audience summary plus distinct pain-point and goal lists.
- Carry `website_analysis.services`, `website_analysis.locations`, and `website_analysis.contact_info` into the card verbatim when available — these are used as factual reference in section writing (Client Context block), not as brand signals.
- Never invent banned/discouraged/preferred terms. If the brand guide does not mention term-level guidance, return empty arrays.

### 2.6 Hallucination Guardrails

- The distillation LLM is **categorization-only**. It may extract, paraphrase, and summarize content present in the input. It must not infer brand preferences not present in the source text.
- All term lists (banned, discouraged, preferred) must be terms or short phrases that appear in or are explicitly named by the input — not the LLM's inferences about what a brand "probably wouldn't like."

### 2.7 Failure Handling

| Scenario | Behavior |
|---|---|
| Distillation LLM returns malformed JSON | One retry with stricter prompt; on second failure, abort run with `brand_distillation_failed` |
| Distillation produces empty card (all fields empty/null) | Continue run; log warning. Section writing proceeds with no brand shaping. |
| `brand_guide_text` is empty string | Skip distillation of brand portion; populate only ICP-derived fields and website-derived fields |
| `icp_text` is empty string | Skip distillation of ICP portion; populate only brand-derived fields |
| Both empty AND `website_analysis_unavailable` is true | Module proceeds as if `client_context` was omitted (v1.4 fallback path); `schema_version` reported as `1.5-degraded` |

---

## 3. New Step 3.5b: Brand–SIE Term Reconciliation

### 3.1 Purpose

Reconcile SIE's `terms.required[]` and `terms.avoid[]` lists against the client's brand-level term preferences. Produce (a) a filtered SIE term list for downstream section writing and (b) the `brand_conflict_log[]` array for the output.

### 3.2 Execution Order

Runs in parallel with Step 3.5a. Consumes `brand_guide_text` directly (not the distilled card, since this step needs full nuance to detect conflicts).

### 3.3 LLM Call

Single LLM call. Input: SIE Required terms list + SIE Avoid terms list + `brand_guide_text`. Output: per-term classification.

### 3.4 Reconciliation Logic

For each SIE-Required term, classify as one of:

| Classification | Trigger | Section-Writing Behavior |
|---|---|---|
| `keep` | No conflict with brand guide | Use at SIE target zone usage (current v1.4 behavior) |
| `exclude_due_to_brand_conflict` | Brand guide explicitly bans the term | Term must not appear anywhere in the article |
| `reduce_due_to_brand_preference` | Brand guide ambiguously discourages without explicit ban | Use at SIE minimum zone usage rather than target |

For each SIE-Avoid term, classify as one of:

| Classification | Trigger | Section-Writing Behavior |
|---|---|---|
| `keep_avoiding` | No brand-guide preference for the term | Continue avoiding |
| `use_due_to_brand_preference` | Brand guide explicitly prefers the term | Use the term despite SIE-Avoid recommendation; log in `brand_conflict_log` as `brand_preference_overrides_sie_avoid` |

**Brand always wins.** Both for Required and Avoid terms:

- **Brand banned > SIE-Required** (brand wins — term excluded)
- **Brand preferred > SIE-Avoid** (brand wins — term used despite SIE recommendation to avoid)

### 3.5 Output: Filtered SIE Term List (Internal)

The reconciliation step produces an internal data structure passed to Step 4:

```json
{
  "filtered_sie_terms": {
    "required": [
      {
        "term": "string",
        "zone_usage_target": int,
        "zone_usage_min": int,
        "zone_usage_max": int,
        "effective_target": int,
        "effective_max": int,
        "reconciliation_action": "keep" | "reduce_due_to_brand_preference"
      }
    ],
    "excluded": [
      {
        "term": "string",
        "original_classification": "required",
        "reason": "exclude_due_to_brand_conflict"
      }
    ],
    "avoid": ["string"]
  }
}
```

When `reconciliation_action` is `reduce_due_to_brand_preference`, `effective_target` equals the original `zone_usage_min` and `effective_max` equals the original `zone_usage_target`. When `reconciliation_action` is `keep`, both fields equal the original SIE values.

### 3.6 Output: Brand Conflict Log (External)

This goes into the Writer's external output. See Section 5 below.

### 3.7 Hallucination Guardrails

- The reconciliation LLM may classify only based on text present in `brand_guide_text`. It must not infer that a term is banned because it "feels" off-brand.
- If the brand guide does not address a term either way, the term is classified `keep` (or `keep_avoiding`).
- The reconciliation LLM must include a `brand_guide_reasoning` string for every non-`keep` classification, citing the specific brand-guide text that triggered the decision.

### 3.8 Failure Handling

| Scenario | Behavior |
|---|---|
| Reconciliation LLM returns malformed JSON | One retry; on second failure, abort with `brand_reconciliation_failed` |
| Reconciliation classifies a term not present in SIE input | Discard the rogue classification; log warning |
| Reconciliation produces empty output (no terms classified) | Treat as all-keep; populate empty `brand_conflict_log` |
| `brand_guide_text` is empty | Skip reconciliation; treat all SIE terms as `keep`; populate empty `brand_conflict_log` |

---

## 4. Modified Steps 4, 5, and 6

### 4.1 Step 4 (Section Writing) — Modifications

The section-writing prompt for each H2/H3 is updated to inject:

| Block | Source | Notes |
|---|---|---|
| **Brand Voice block** | `brand_voice_card.tone_adjectives` + `voice_directives` | Compact directive list, ≤500 chars in prompt |
| **Audience block** | `brand_voice_card.audience_summary` + `audience_pain_points` | Helps frame phrasing toward ICP |
| **Client Context block** | `brand_voice_card.client_services` + `client_locations` + `positioning_statement` | Used only when website_analysis was available; enables natural references to client offerings without forcing them |
| **Filtered SIE terms** | `filtered_sie_terms.required` (filtered for terms applicable to this section) | Replaces the raw SIE Required list previously passed in v1.4 |
| **SIE-Excluded terms (informational)** | `filtered_sie_terms.excluded` (filtered for terms applicable to this section) | Listed as "do not use" with brief rationale, so the LLM does not regress to using them |

**Behavioral rules unchanged from v1.4:**
- Citation marker placement (`{{cit_N}}`) per Step 4F
- Word-count budgeting per section
- Heading-level adherence (H2/H3 boundaries)
- Required vs. exploratory term coverage targets

**New behavioral rules in v1.5:**
- The section must read as if written for the ICP described in the audience block, using the tone described in the brand voice block
- The section must not use any term in `filtered_sie_terms.excluded` that applies to this section's scope
- The section may reference client services or locations from the Client Context block where natural; it must not force-fit them
- When the Client Context block is empty (website_analysis_unavailable), the section writes without any client-specific positioning

### 4.2 Step 5 (FAQ Writing) — Modifications

FAQs are reframed to match what the ICP would actually ask. Prompt additions:

| Block | Source | Notes |
|---|---|---|
| **Audience block** | `brand_voice_card.audience_summary` + `audience_pain_points` + `audience_goals` | The full audience picture, not just summary — FAQs are highly audience-shaped |
| **Brand Voice block** | `brand_voice_card.tone_adjectives` + first 3 voice_directives | Lighter than section-writing injection because FAQ answers are shorter |
| **Filtered SIE terms** | `filtered_sie_terms.required` | Same as section writing |

**New behavioral rules:**
- FAQ questions must reflect the ICP's actual phrasing patterns, not generic SEO question templates
- Answers respect tone and banned-terms rules identically to section writing

### 4.3 Step 6 (Intro/Conclusion Writing) — Modifications

Intros and conclusions get the heaviest brand shaping because they set the article's voice and positioning. Prompt additions:

| Block | Source | Notes |
|---|---|---|
| **Brand Voice block** | Full `brand_voice_card.tone_adjectives` + `voice_directives` | Most brand-loaded section of article |
| **Audience block** | `brand_voice_card.audience_summary` only | Conclusions are not pain-point-heavy |
| **Client Context block** | `brand_voice_card.client_services` + `brand_voice_card.client_locations` | When available; enables natural service-area references in conclusion. Used only when `website_analysis_unavailable` is false. |

**New behavioral rules:**
- Intro must not include company-specific positioning or sales framing in the first 100 words
- Conclusion may include a natural closing sentence referencing client services or location where contextually relevant; never a hard sales CTA
- Both must respect banned-terms rules identically to section writing
- **No positioning statement is injected** — website analysis does not produce one; brand tone and voice from `brand_guide_text` drive the conclusion's character

### 4.4 Post-Hoc Banned-Term Validation (Regex-Based)

Per **Decision D2**, banned-term detection in generated output is regex-based.

#### 4.4.1 Regex Construction

After all section, FAQ, intro, and conclusion writing completes — but before the run is finalized — the Writer constructs a single regex pattern from `brand_voice_card.banned_terms`:

```python
import re

banned_terms = brand_voice_card["banned_terms"]
if banned_terms:
    # Escape each term, join with alternation, wrap in word boundaries
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in banned_terms) + r")\b"
    banned_regex = re.compile(pattern, re.IGNORECASE)
else:
    banned_regex = None  # No validation needed
```

#### 4.4.2 Scan Targets

The regex runs against each of the following content fields independently:

| Field | Scan Target |
|---|---|
| `article[].h1` | Title text |
| `article[].h2` | Each H2 heading |
| `article[].h3` | Each H3 heading |
| `article[].body` | Section body text (citation markers `{{cit_N}}` ignored — they don't contain banned terms by construction) |
| Intro paragraphs | Full text |
| Conclusion paragraphs | Full text |
| FAQ questions | Each question |
| FAQ answers | Each answer |

#### 4.4.3 Match Behavior

| Match Location | Severity | Behavior |
|---|---|---|
| Match in any heading (`h1`, `h2`, `h3`) | **Critical** | Abort with `banned_term_leakage` immediately; do not retry. Headings are too short to require regeneration heuristics. Surface the offending term and heading text in the error. |
| Match in a body section, intro, conclusion, or FAQ answer | **Recoverable** | Retry that single content unit once with a stricter prompt that lists the specific banned term to avoid. If the retry still produces a match, abort with `banned_term_leakage`. |
| Match in a FAQ question | **Recoverable** | Same retry-once policy as body content |

#### 4.4.4 Edge Cases & Limitations

| Case | v1.5 Behavior | Notes |
|---|---|---|
| Banned term contains hyphens (e.g., `"high-quality"`) | Matches exact form only | Variants like `"high quality"` (no hyphen) will not match in v1.5; document this limitation in module docs |
| Banned term is a multi-word phrase (e.g., `"cutting edge"`) | Matched as a literal phrase with word boundaries on outer characters | `"cutting-edge"` and `"cuttingedge"` will not match |
| Banned term as substring of allowed word (e.g., banned `"art"` matches inside `"smart"`) | Word-boundary regex prevents this match | Regex uses `\b...\b` precisely to avoid this class of false positive |
| Possessives, plurals, conjugations (e.g., banned `"premium"` and article uses `"premium's"` or `"premiums"`) | The plural/possessive forms also match because `\b` boundaries treat punctuation as separators | Acceptable for v1.5; refinement deferred to v1.6 |
| Case variations (`"Premium"`, `"PREMIUM"`) | Matched via `re.IGNORECASE` flag | |
| Banned term appears inside a citation marker token (`{{cit_N}}`) | Cannot occur — markers conform to `\{\{cit_[0-9]+\}\}` and contain no banned-term text | |

#### 4.4.5 Output Reporting

When a regex match triggers a successful retry (i.e., the retry produced clean content), the original leakage is logged in the run's structured logs but **not** surfaced in the user-facing output — the user sees only clean content. When a match triggers an abort, the failure mode `banned_term_leakage` is reported with the offending term, the field name, and a snippet of the offending text.

---

## 5. Output Schema Additions

### 5.1 New Top-Level Output Fields

```json
{
  "schema_version": "1.5",
  "article": [...],
  "citations": [...],
  "citation_usage": {...},
  "brand_voice_card_used": {
    "tone_adjectives": ["..."],
    "voice_directives": ["..."],
    "audience_summary": "...",
    "audience_pain_points": ["..."],
    "audience_goals": ["..."],
    "preferred_terms": ["..."],
    "banned_terms": ["..."],
    "discouraged_terms": ["..."],
    "positioning_statement": "...",
    "client_services": ["..."],
    "client_locations": ["..."]
  },
  "brand_conflict_log": [
    {
      "term": "string",
      "sie_classification": "required" | "avoid",
      "resolution": "exclude_due_to_brand_conflict" | "reduce_due_to_brand_preference" | "brand_preference_overridden_by_sie",
      "brand_guide_reasoning": "string (≤300 chars)",
      "applicable_section_ids": ["string"]
    }
  ],
  "client_context_summary": {
    "brand_guide_provided": true,
    "icp_provided": true,
    "website_analysis_used": true,
    "schema_version_effective": "1.5" | "1.5-no-context" | "1.5-degraded"
  }
}
```

### 5.2 Field Semantics

| Field | Notes |
|---|---|
| `brand_voice_card_used` | The exact distilled brand voice card that drove section writing. Verbatim copy from Step 3.5a output. Surfaced for downstream review and debugging. |
| `brand_conflict_log` | One entry per non-`keep` reconciliation decision from Step 3.5b. Empty array (`[]`) when no conflicts existed. **Never null.** |
| `brand_conflict_log[].applicable_section_ids` | Section IDs (from Brief input) where the term would have been used per SIE; empty list if the term applied article-wide |
| `client_context_summary` | Quick-reference flags indicating which inputs were used; `schema_version_effective` reflects which path the module took |

### 5.3 Modified Existing Output Fields

`schema_version` bumps from `1.4` to `1.5`. No other existing fields are modified.

`citation_usage`, `article[]`, `citations[]` retain their v1.4 schemas and behavior.

---

## 6. Updated Business Rules

Add to existing Section 11 (Business Rules):

| Rule | Value |
|---|---|
| Client context input | Optional; when present, v1.5 behavior is mandatory |
| Brand guide / ICP format | JSON or Markdown preferred; plain text accepted for PDF/DOCX uploads; max 150,000 characters per field |
| Brand voice card source | Tone adjectives and voice directives come exclusively from `brand_guide_text` — never from `website_analysis` |
| Website analysis in brand voice card | Provides `client_services`, `client_locations`, and `client_contact_info` only — factual reference data, not brand signals |
| Brand voice card persistence | Surfaced verbatim in output as `brand_voice_card_used` for auditability |
| **Brand always wins** | Brand banned > SIE-Required (term excluded). Brand preferred > SIE-Avoid (term used). No exceptions. |
| Reconciliation grounding | Reconciliation LLM must cite specific brand-guide text in `brand_guide_reasoning`; cannot infer banned/preferred status without supporting text |
| Distillation grounding | Distillation LLM may extract and summarize only; may not invent brand opinions |
| Empty brand context handling | If both `brand_guide_text` and `icp_text` are empty AND `website_analysis_unavailable` is true, fall back to v1.4 behavior with `schema_version: "1.5-degraded"` |
| Backward compatibility | Omitted `client_context` input falls back to v1.4 behavior with `schema_version: "1.5-no-context"` |
| Prompt injection size cap | Brand voice card injected into section/FAQ/conclusion prompts is bounded by the schema field limits (Section 2.4) — never the raw 150,000-char inputs |
| Section banned-term enforcement | Sections must contain zero occurrences of any term in `brand_voice_card.banned_terms` or in the `filtered_sie_terms.excluded` list. Enforcement mechanism is regex-based, case-insensitive, with word boundaries (per Decision D2 and Section 4.4) |
| Heading banned-term enforcement | Headings (h1, h2, h3) must also exclude banned terms. Heading-level matches abort the run immediately with no retry (per Section 4.4.3) |
| Brand voice card lifecycle | Regenerated per run from current snapshot; never cached on the client record (per Decision D1). Persisted to Supabase as part of the run's `module_outputs` record via the `brand_voice_card_used` output field. |
| Citation handling | Unchanged from v1.4 |
| Marker placement | Unchanged from v1.4 |

---

## 7. Updated Failure Modes

Add to existing failure modes:

| Scenario | Behavior |
|---|---|
| `client_context` omitted from input | Continue with v1.4 fallback; `schema_version: "1.5-no-context"` |
| `client_context` present but malformed (missing required fields) | Abort with `client_context_validation_error` |
| Brand distillation LLM fails twice | Abort with `brand_distillation_failed` |
| Brand reconciliation LLM fails twice | Abort with `brand_reconciliation_failed` |
| Distillation produces empty card across all fields | Continue; log warning; section writing proceeds without brand shaping |
| Reconciliation produces no conflicts (all `keep`) | Continue; emit empty `brand_conflict_log`; this is the expected case for clients with no term-level brand rules |
| Section writing produces output containing a banned term (post-hoc regex validation) | Re-run that section once with stricter prompt naming the specific banned term; if the retry still matches, abort with `banned_term_leakage` and surface offending term + section + snippet in the error (per Section 4.4) |
| Heading produced contains a banned term (post-hoc regex validation) | Abort immediately with `banned_term_leakage`; no retry (per Section 4.4.3); surface offending term and heading text |
| `website_analysis_unavailable` is true | Continue normally; skip Client Context block in all prompts; Positioning block in conclusion is skipped |
| ICP empty but brand guide present | Continue; audience block in prompts is replaced with a generic "general professional reader" placeholder; logged as warning |
| Brand guide empty but ICP present | Continue; brand voice block in prompts is replaced with a neutral-tone placeholder; logged as warning |

---

## 8. Updated Cost & Timing

### 8.1 Added LLM Calls

| Step | Calls | Notes |
|---|---|---|
| 3.5a Brand Distillation | 1 | Single LLM call, moderate input size |
| 3.5b Brand–SIE Reconciliation | 1 | Single LLM call, smaller input than distillation |
| Banned-term re-runs (Step 4 retry) | 0–N | Only triggered on banned-term leakage; expected near-zero in practice |

### 8.2 Cost Impact

Estimated per-article cost increase from v1.4: **+$0.04 to +$0.08**, driven by the two new preprocessing LLM calls plus modest section-prompt token increase from injected brand voice cards.

| Component | v1.4 | v1.5 | Delta |
|---|---|---|---|
| Section writing total | $0.22–$0.36 | $0.24–$0.39 | +$0.02–$0.03 |
| FAQ writing | $0.04–$0.05 | $0.04–$0.05 | unchanged |
| Intro/conclusion | $0.02–$0.03 | $0.02–$0.03 | unchanged |
| **Brand distillation (new)** | — | $0.02–$0.04 | new |
| **Brand reconciliation (new)** | — | $0.01–$0.02 | new |
| **Total Writer cost per article** | $0.28–$0.43 | $0.32–$0.51 | +$0.04–$0.08 |

The platform PRD's $0.75 ceiling for the Writer module remains comfortably above the v1.5 ceiling.

### 8.3 Timing Impact

Steps 3.5a and 3.5b run in parallel. Each takes ~5–15 seconds. Because they run before section writing, they extend the Writer's wall-clock time by their parallel completion duration.

| Stage | v1.4 (sec) | v1.5 (sec) |
|---|---|---|
| Preprocessing (3.5a + 3.5b parallel) | 0 | 5–15 |
| Section writing | 30–50 | 30–50 |
| FAQ + Intro + Conclusion | 10–20 | 10–20 |
| Step 7 (citation reconciliation) | 5–10 | 5–10 |
| **Total** | 45–80 | 50–95 |

The platform PRD's 90-second max for the Writer module remains the operative ceiling; v1.5 fits within it.

---

## 9. Migration & Rollout Notes

### 9.1 Breaking Changes

- **No** breaking changes for callers that omit `client_context` — those continue receiving v1.4 behavior under `schema_version: "1.5-no-context"`.
- **Breaking** for callers that send `client_context` — they must conform to the new Input D schema. The platform's orchestrator (per Platform PRD v1.2 §8) will be the only caller sending this input in production.

### 9.2 Suggested Test Fixtures

To validate v1.5 in isolation before platform integration, the team should produce:

1. **Fixture A — No client context**: Existing v1.4 fixtures continue to pass with `schema_version: "1.5-no-context"`.
2. **Fixture B — Empty client context**: All three fields populated as empty strings + `website_analysis_unavailable: true`. Should produce `schema_version: "1.5-degraded"`.
3. **Fixture C — Brand guide only**: Populated `brand_guide_text` with explicit banned terms; empty ICP; no website analysis. Verify `brand_conflict_log` populates and banned terms do not appear in output.
4. **Fixture D — Full client context**: All fields populated. Verify section tone shifts visibly when running same Brief/SIE inputs against two different brand guides.
5. **Fixture E — Banned term that is also SIE-Required**: Verify reconciliation excludes it and `brand_conflict_log` records the decision with cited brand-guide reasoning.
6. **Fixture F — SIE-Avoid term that brand guide prefers**: Verify SIE wins, term remains absent, and `brand_conflict_log` records the override.
7. **Fixture G — Banned term leakage attempt (regex validation)**: Construct a brand guide with a common term banned (e.g., "affordable") that section writing might naturally use. Verify post-hoc regex catches the term, the section retries once with the term explicitly named in the prompt, and either (a) the retry produces clean content or (b) abort fires with `banned_term_leakage` containing the offending term, field name, and snippet.
8. **Fixture H — Banned term in heading (regex validation)**: Construct a brand guide that bans a term likely to appear in a heading (e.g., banning "cheap" when the keyword involves price). Verify the run aborts immediately on heading match without any retry.
9. **Fixture I — Word boundary edge cases**: Construct a brand guide that bans `"art"` and a section likely to use `"smart"`. Verify the regex word boundaries prevent false positives — `"smart"` should pass; standalone `"art"` should fail.

### 9.3 Module Version Bump

Update module manifest to `1.5`. Update Section 14 of master PRD with the entry below.

---

## 10. New Section 14 Entry (Ready to Append)

Append this row to the existing version history table in Section 14 of the master Writer Module PRD:

| Version | Date | Notes |
|---|---|---|
| 1.5 | 2026-04-30 | Added Input D (`client_context`) carrying `brand_guide_text`, `icp_text`, and `website_analysis` from the platform layer. Added Step 3.5a (Brand Voice Distillation) and Step 3.5b (Brand–SIE Term Reconciliation), running in parallel before Step 4. Brand voice card is regenerated per run from the platform's `client_context_snapshots` (no caching on the client record); the resulting card is persisted to Supabase via the `brand_voice_card_used` output field. Section writing, FAQ writing, and intro/conclusion writing prompts now inject distilled brand voice card, audience summary, filtered SIE terms, and (when available) website-derived client context blocks. Added output blocks `brand_voice_card_used`, `brand_conflict_log[]`, and `client_context_summary`. Added precedence rules: brand-banned > SIE-Required (term excluded), SIE-Avoid > brand-preferred (continue avoiding). Distillation and reconciliation LLMs are categorization-only — both must ground decisions in source text and may not invent brand opinions. Added post-hoc banned-term validation: regex-based, case-insensitive, word-boundary matching against `brand_voice_card.banned_terms`. Headings on regex match abort immediately with no retry; body/FAQ/intro/conclusion matches retry once with stricter prompt before aborting. Added backward-compat fallback `schema_version: "1.5-no-context"` when `client_context` is omitted, and `schema_version: "1.5-degraded"` when all client context is empty. Added three new failure modes (`brand_distillation_failed`, `brand_reconciliation_failed`, `banned_term_leakage`). Estimated cost delta from v1.4: +$0.04 to +$0.08 per article. Bumped output `schema_version` to `1.5`. |

---

## 11. Open Questions

The following questions remain open after the v1.5 review. (Questions on brand voice card caching and banned-term detection mechanism have been resolved — see Decisions Resolved section at top of this document.)

| # | Question | Recommendation |
|---|---|---|
| 1 | Should `discouraged_terms` from the brand voice card flow into reconciliation, or only `banned_terms`? | Only `banned_terms` for hard exclusion; discouragement is handled by the reconciliation LLM directly reading `brand_guide_text`, which produces `reduce_due_to_brand_preference` decisions. This is already covered. |
| 2 | When `website_analysis_unavailable` is true, should the conclusion still attempt brand-aligned closing? | Yes, using only `brand_voice_card.tone_adjectives` and `voice_directives` — no positioning statement |
| 3 | Should the platform see distillation LLM cost separately from reconciliation cost in cost dashboards? | Yes — both should be tagged distinctly so the team can isolate cost of brand handling from cost of writing |
| 4 | Is the 30-item cap on `banned_terms` sufficient for typical brand guides? | Likely yes; enterprise brand books may exceed this, but v1.5 is for SMB clients. Revisit if breaches occur. |
