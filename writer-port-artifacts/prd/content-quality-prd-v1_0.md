# PRD: Content Quality Requirements

**Version:** 1.0 (Draft)
**Status:** Draft — Ready for Implementation
**Last Updated:** 2026-05-01
**Audience:** Engineering team
**Modules in Scope:**
- Content Brief Generator (v1.7 → v1.8)
- Content Writer Module (v1.5 → v1.6)
- Platform layer (per-client context flow)

---

## 1. Background

This PRD encodes content-quality requirements identified during a production-quality audit of a generated article on the keyword `tiktok shop` (run dated 2026-05-01). The audit surfaced concrete failure modes that must not recur:

| Failure | Symptom in audited run |
|---|---|
| Heading-set redundancy | 9 H2s all paraphrased the same definitional question ("What is TikTok Shop", "What exactly is TikTok Shop", "Explained: What is TikTok Shop", etc.) |
| SERP-artifact leakage | Headings included subreddit suffixes (`: r/TikTokshop`), ellipsis (`How's it Different ...`), and pipe-separated site names (`TikTok Shop \| Discover the Future of Social Commerce`) |
| Topic drift | Two H2s on tangential topics (US-ban data implications, internal algorithm mechanics) padded a piece whose title promised a definition |
| Missing structural elements | No Key Takeaways block at top, no opening Agree / Promise / Preview construction, no closing CTA |
| Brand context absent | Article had zero brand mentions and no audience framing despite a configured client |
| Paragraph length | Several paragraphs ran past four sentences |
| Citation thinness | Multiple factual / time-bound claims with no external citation |

Every requirement below maps to one or more of the failures above. This PRD is the source of truth for the *what*; the module PRDs (Brief v1.8, Writer v1.6) carry the *where and how*.

---

## 2. Requirements

### R1 — Semantic Heading Deduplication

**What:** H2s that paraphrase the same question or assert the same definition must collapse to a single section in the final outline.

**Why:** The Brief Generator's Levenshtein-based dedup (ratio ≤ 0.15) catches lexical near-duplicates but misses semantic ones. Eight to ten "What is X?" rephrasings will all survive that filter and then sweep the priority-ranked H2 selection because semantic similarity to the keyword is 40% of the priority score.

**Acceptance criteria:**
- After the Brief Generator's heading-selection step, no two surviving H2s may have a cosine similarity ≥ **0.85** to each other (using the same `text-embedding-3-small` vectors already computed in Step 5).
- Selection must apply Maximum Marginal Relevance (MMR) ranking: each candidate H2 is scored as `λ·heading_priority − (1−λ)·max_cosine_to_already_selected_H2s`. Default `λ = 0.6` (favors topical diversity over raw priority).
- When two candidates exceed the 0.85 threshold, retain the one with the higher `heading_priority`; the loser is moved to `discarded_headings` with `discard_reason: "semantic_duplicate_of_higher_priority_h2"` and a back-reference field `semantic_duplicate_of: <order>`.
- A run that begins with ≥ 6 candidates whose pairwise similarity to the seed keyword is ≥ 0.90 (i.e., a definitional keyword like "what is X") must produce **at most one** H2 of the form "What is X / What does X mean / Define X / Explain X". Additional definitional rephrasings are discarded with `discard_reason: "definitional_restatement"`.
- The `metadata` block of the brief output reports `semantic_dedup_collapses_count` and `definitional_restatements_discarded_count`.

**Owning module:** Content Brief Generator (Steps 4, 5, 8). See Brief PRD §5 for placement.

---

### R2 — SERP Heading Sanitization

**What:** Headings ingested from SERP scraping, autocomplete, keyword suggestions, and LLM responses must be sanitized of artifacts before scoring or selection.

**Why:** Raw SERP H2s frequently carry boilerplate that pollutes the final article — subreddit suffixes, source-name pipes, trailing ellipsis, "Read more" suffixes. The current pipeline strips a small fixed list of boilerplate phrases ("Contact Us", "About the Author", "Related Posts") but does not normalize these patterns.

**Acceptance criteria:** All of the following sanitization rules are applied to **every heading candidate** at the start of Step 4 (Subtopic Aggregation), before normalization, dedup, embedding, scoring, or polish:

| # | Pattern | Action |
|---|---|---|
| S1 | Trailing `: r/<subreddit>` (e.g., `: r/TikTokshop`) | Strip suffix |
| S2 | Trailing `…` or three or more consecutive periods (`...`, `....`) | Strip suffix |
| S3 | Trailing `\| <site name>` or `– <site name>` or `— <site name>` (em/en dash) where the trailing segment matches a domain root in the SERP item's URL or is < 30 characters and contains at most one CapitalizedWord run | Strip suffix |
| S4 | Leading `<site name>: ` (same matching rule as S3) | Strip prefix |
| S5 | Trailing `\| Read More`, `\| Continue Reading`, `Read More …`, `Continue Reading …` | Strip suffix |
| S6 | Wrapping HTML tags or entities (`<strong>`, `&amp;`, `&#8217;`) | Decode entities; strip tags |
| S7 | Multiple internal whitespace runs (e.g., `What  is  X`) | Collapse to single spaces |
| S8 | Trailing punctuation runs (`?!`, `?.`, `..`) other than a single terminal `?` or `.` | Reduce to single terminal mark |
| S9 | Headings shorter than 3 words after sanitization | Discard with `discard_reason: "too_short_after_sanitization"` |
| S10 | Headings whose sanitized form is a single proper-noun brand name with no verb or noun phrase (e.g., `TikTok Shop` alone, `Salesforce`) | Discard with `discard_reason: "non_descriptive_after_sanitization"` |

- Sanitization is applied **before** Levenshtein dedup so near-duplicates that previously differed only by their suffixes now collapse correctly.
- Sanitization is **also applied** to the `original_text` saved on the candidate, but the pre-sanitization raw text is preserved on the candidate object as `raw_text` so the brief output's `discarded_headings[].original_source` can show what was scraped.
- The polish-pass LLM (Step 5) receives sanitized text only; it must not be asked to clean SERP artifacts because that responsibility now belongs to the deterministic sanitization step.

**Owning module:** Content Brief Generator (Step 1 boilerplate strip extended; Step 4 pre-aggregation sanitization). See Brief PRD §5 for placement.

---

### R3 — Topic Adherence and Spin-Off Routing

**What:** Sections whose topic does not directly serve the article's title promise must be excluded from the parent piece. Off-topic but related content must be routed into a separate `spin_off_articles` output for future pieces, never padded into the parent piece.

**Why:** The audited run included "What happens to your purchase data … if TikTok faces a US ban" and "How TikTok Shop's algorithm decides which products get shown" in a piece whose title promised a definition. Both topics are interesting follow-ups; neither serves the parent piece's reader intent.

**Acceptance criteria:**

| Criterion | Detail |
|---|---|
| Title-promise embedding | After Step 1 (Title Generation) in the Writer Module, the title is embedded with `text-embedding-3-small`. Each H2 candidate's `topic_adherence_score` is the cosine similarity between its embedding (computed earlier in the brief) and the title embedding. |
| Adherence threshold | An H2 with `topic_adherence_score < 0.62` is removed from the writer's section-writing queue, regardless of its `heading_priority` from the brief. The H2 is logged in writer metadata as `dropped_for_low_topic_adherence` with the score. |
| Authority gap H3 exemption | Authority gap H3s (`source: "authority_gap_sme"`) bypass this check — they are by design tangential and exist to add expert depth, but they remain attached to a parent H2 that itself passed the adherence check. |
| Spin-off routing | Any H2 dropped for low topic adherence, plus any heading already in `discarded_headings` with `discard_reason` ∈ {`global_cap_exceeded`, `below_priority_threshold`, `definitional_restatement`}, is candidates for spin-off. The Brief Generator's existing Step 9 (silo identification) is renamed and re-purposed to populate `spin_off_articles[]` (see R3 schema below). |
| Reader-intent alignment | The Writer Module's per-H2 system prompt receives the title verbatim and a one-sentence framing of who the piece is for (drawn from `client_context.icp_text`). H2 sections that do not serve that intent in their first sentence trigger a one-shot retry with a stricter prompt; on second failure the section is dropped and logged. |

**Schema addition (Brief output):**
```json
"spin_off_articles": [
  {
    "suggested_keyword": "how tiktok shop's algorithm ranks products",
    "source_heading_text": "How TikTok Shop's algorithm decides which products get shown to which buyers",
    "source_reason": "low_topic_adherence | semantic_duplicate | global_cap_exceeded | below_priority_threshold",
    "topic_adherence_score": 0.41,
    "recommended_intent": "informational",
    "supporting_headings": ["string"]
  }
]
```

The legacy `silo_candidates[]` field is retained for one release with identical content as `spin_off_articles[]` for backward compatibility, then removed in v1.9 of the brief.

**Owning modules:** Brief Generator (spin-off routing in Step 9), Writer Module (topic-adherence enforcement after Step 1). See Brief PRD §5 and Writer PRD §6.

---

### R4 — Required Structural Elements

**What:** Every generated article must include all three of the following structural elements. Absence of any element is a hard failure of the writer module.

| Element | Required Position | Required Content |
|---|---|---|
| **Key Takeaways** | Immediately after H1 enrichment, before the first content H2 | A bulleted list of 3–5 standalone sentences, each ≤ 25 words, that summarize the article's most extractable claims. Optimized for AEO snippet capture. |
| **Agree / Promise / Preview intro** | The intro paragraph(s) directly following the Key Takeaways block, before the first H2 | Three discrete prose blocks: (a) **Agree** — a sentence acknowledging the reader's situation or question; (b) **Promise** — a sentence stating what the article will deliver; (c) **Preview** — a sentence enumerating 2–4 sub-topics covered. Each block is ≤ 50 words. |
| **CTA** | Final sentence of the conclusion section | A clear next-step call-to-action sentence that names a specific action a reader can take, drawn from `client_context.icp_text` goals when available, or from a generic intent-appropriate template otherwise. Never a hard sales pitch. |

**Acceptance criteria:**
- The writer's output schema gains three new fields under the article assembly: `key_takeaways: [string]`, `intro: { agree: string, promise: string, preview: string }`, and `cta: string`.
- The article assembly emits these as ordered sections in `article[]` so downstream renderers see a consistent structure:
  - `{order, level: "none", type: "key-takeaways", heading: "Key Takeaways", body: "<bulleted markdown>"}` — `heading` is rendered as H2 by the renderer.
  - `{order, level: "none", type: "intro", heading: null, body: "<APP prose, three paragraphs>"}` — three paragraphs separated by blank lines.
  - `{order, level: "none", type: "cta", heading: null, body: "<single CTA sentence>"}` — appended after the conclusion section.
- A run whose final article is missing any of the three sections aborts with structured error `missing_required_structure` and a `missing_elements: [...]` list. No partial output is returned.
- The Key Takeaways block is generated **after** all content sections and the conclusion are written (so it summarizes actual content, not the outline). It is a single LLM call that takes the full article body as input.
- Renderer responsibilities (frontend `sectionsToMarkdown`): the `type: "key-takeaways"` section heading is rendered as `## Key Takeaways`; the `type: "intro"` body is inserted between H1 and the first H2 with no heading prefix; the `type: "cta"` body is appended as the article's last paragraph with no heading prefix.

**Owning module:** Content Writer Module. See Writer PRD §6 (new Step 1.5, modified Step 2, modified Step 6, new Step 6.5).

---

### R5 — Brand Context Injection

**What:** Per-client brand and ICP context must reach every generation prompt across the full pipeline (Brief Generator topic adherence prompt, Writer Module section/FAQ/intro/conclusion prompts). Brand mentions in the final article are budgeted, not unlimited; missing brand mentions on brand-aligned topics are flagged for review, not auto-rejected.

**Why:** The platform already snapshots `client_context` per run, but only the Writer Module currently consumes it (per v1.5 spec). The Brief Generator runs blind to client identity, which lets it produce headings that drift entirely off-brand. The audited run had zero brand mentions in the final article despite the configured client having an explicit ICP and brand voice.

**Acceptance criteria:**

| Criterion | Detail |
|---|---|
| Canonical ICP source | The platform's per-client `client_context_snapshots.icp_text` is the source of truth at run time. A reusable agency-wide default ICP guide may be loaded from `/config/ubiquitous_icp_guide.json` (or an env-pointed path) and merged with per-client `icp_text` at snapshot creation; per-client always takes precedence on conflicts. The exact path is to be confirmed in the engineering spec; until then, a per-client `icp_text` is sufficient. |
| Brief Generator receives client context | The Brief Generator's input gains an optional `client_context` field (same schema as the Writer's `client_context`). When present, the topic-adherence enforcement (R3) uses ICP audience framing in its title-vs-section relevance check. Headings that score in the bottom 25% on adherence and **also** semantically clash with the ICP audience description (cosine ≤ 0.45 to the audience summary embedding) are downgraded by 0.10 in `heading_priority` before MMR selection. |
| Writer prompts already covered | Writer v1.5 already injects `client_context` into Steps 4, 5, 6. v1.6 extends this to the new Key Takeaways and CTA generation steps (R4). |
| Brand mention budget | The final article must contain **2–3** brand-name mentions where the brand is named in the client's `brand_voice_card.client_services` or recognized as the client's own brand from `brand_guide_text` heading text. Mention count is enforced post-hoc: |
| | – If count is 0 and the topic is *brand-aligned* (defined: title cosine ≥ 0.55 to the brand voice card's `client_services` joined string), flag `zero_brand_mentions_on_brand_aligned_topic` in writer metadata. **Do not auto-reject.** |
| | – If count is 0 and the topic is *not* brand-aligned (cosine < 0.55), no flag. Writing brand-agnostic top-of-funnel content with zero mentions is intentional. |
| | – If count is 1, no action. |
| | – If count is 4–5, log warning `brand_mentions_exceed_target` but do not reject. |
| | – If count is ≥ 6, retry the highest-mention section once with a stricter prompt that lists the limit; on second failure, log `brand_mentions_exceed_hard_cap` and accept the output (do not block publishing). |
| Brand-aligned vs. brand-agnostic flag | Writer metadata gains `topic_brand_alignment: "brand_aligned" \| "brand_agnostic"` based on the cosine threshold above. |

**Owning modules:** Platform layer (snapshot + global ICP merge), Brief Generator (consume `client_context` for adherence check), Writer Module (extend existing v1.5 client-context flow to new steps + brand-mention budget).

---

### R6 — Paragraph Length Cap

**What:** Hard cap of 4 sentences per paragraph in any generated content section, FAQ answer, intro block, conclusion, or CTA. Three sentences or fewer is the preferred shape.

**Why:** Long paragraphs reduce readability, hurt mobile rendering, and lower extractability for LLM citation surfaces. The audited run had paragraphs running 5–7 sentences in multiple sections.

**Acceptance criteria:**
- After all content generation completes (and before banned-term scanning, which already runs as a post-hoc pass), the Writer performs a **paragraph length validation** pass:
  - Split each `body` field on blank lines (markdown paragraph boundaries).
  - For each paragraph, count sentence-terminal punctuation (`.`, `?`, `!`) outside markdown link/code spans. A run of consecutive `.`s (e.g., inside `e.g.`, abbreviations, URLs) is collapsed first using a small abbreviation dictionary (`e.g.`, `i.e.`, `etc.`, `Mr.`, `Dr.`, `vs.`, `Inc.`, `U.S.`, `U.K.`).
  - If any paragraph has > 4 sentences, mark the section for retry.
- Each over-budget section is retried **once** with a prompt addendum: `"Critical: every paragraph must contain at most 4 sentences. Three sentences or fewer is preferred. If a paragraph runs longer, split it on a logical break."` The retry replaces the section in the article.
- If the retry is also over budget, no further retry is attempted; the section is accepted but flagged in writer metadata `paragraph_length_violations: [{section_order: int, max_sentences: int}]`.
- The validation pass scans Key Takeaways bullets too: any single bullet > 25 words triggers a one-time retry of the Key Takeaways generation with a strict word limit reminder.
- Format-directive metadata gains `max_sentences_per_paragraph: 4` in the brief's `format_directives` so the section-writing prompts include the constraint **upstream** of the validation check (reducing retry frequency).

**Owning module:** Content Writer Module (post-generation validation, new Step 6.6). See Writer PRD §6.

---

### R7 — External Citations on Factual Claims

**What:** When the article makes time-bound, statistical, percentage, named-brand, or named-study claims, at least some of those claims must be backed by external citations. First-party sources are preferred over secondary aggregators.

**Why:** Articles without citations on factual claims are weaker for AEO (LLMs trust cited content more), weaker for SEO (E-E-A-T signals), and create legal exposure when claims are wrong. The audited run had multiple statistic-bearing sentences ("surpassed $100 million in U.S. sales within its first month") without citations on the section itself.

**Acceptance criteria:**

| Criterion | Detail |
|---|---|
| Claim detection | After section writing, the Writer runs a deterministic pass over each section body to count **citable claims**. A claim is detected when any of the following patterns match a sentence: |
| | (a) a numeral followed by `%`, `percent`, `pct`, or `percentage points` |
| | (b) a numeral with currency symbol or USD/EUR/GBP suffix (e.g., `$100M`, `€50`, `1.2 billion USD`) |
| | (c) a four-digit year between 1990 and 2099 used as a date (`in 2023`, `since 2024`) |
| | (d) `according to <ProperNoun>`, `<ProperNoun> reports`, `<ProperNoun> found`, `<ProperNoun> survey` |
| | (e) `studies show`, `research shows`, `data shows`, `analysts predict` |
| | (f) any sentence containing the name of a public figure, company, or product (resolved via the SIE entity list: `sie.terms.required[*].is_entity == true`) **and** a quantitative or temporal qualifier from (a)–(c) |
| Coverage threshold | At least **50%** of detected citable claims in a section must be followed by a `{{cit_id}}` marker (existing v1.4+ marker convention). The threshold is per-section, not per-article. |
| First-party preference | When the Research module produced multiple citation candidates for a claim, the Writer prefers citations whose `domain` matches the entity named in the claim sentence (e.g., a claim mentioning `Forbes` prefers a Forbes URL over a third-party summary of the same data). The Research module's `citations[]` already carries domain in v1.1 — this is a writer-side selection rule, not a research-side change. |
| Below-threshold remediation | A section that fails the 50% threshold triggers a one-shot retry with a stricter prompt that names the uncited claim sentences and asks the LLM to either (a) add a citation marker for that claim from the available citation pool, or (b) rewrite the sentence to remove the specific statistic / year / brand attribution if no citation supports it. |
| Failure logging | If the retry still fails the threshold, the section is accepted but flagged in writer metadata: `under_cited_sections: [{section_order: int, citable_claims: int, cited_claims: int}]`. |
| FAQ exemption | FAQ answers are exempt from the 50% threshold because they are intentionally generic-knowledge restatements; however, the same claim-detection pass runs on FAQ answers and any FAQ answer with a numeric statistic without a citation is **rewritten** to remove the statistic in favor of a qualitative phrasing. |

**Owning modules:** Content Writer Module (claim detection + threshold enforcement), Research & Citations Module (no schema change required; existing citations are already keyed by domain).

---

## 3. Module Impact Summary

| Module | Affected | Document(s) updated |
|---|---|---|
| Brief Generator | R1, R2, R3, R5 | `/docs/modules/content-brief-generator-prd-v1.7.md` (bumped to v1.8) |
| Writer Module | R3, R4, R5, R6, R7 | `/docs/modules/content-writer-module-prd-v1.3.md` (bumped to v1.6) |
| Platform | R5 | `/docs/content-platform-prd-v1_3.md` (bumped to v1.4) |
| Sources Cited | None — outputs unchanged | n/a |
| Research & Citations | None — schema unchanged; v1.6 writer adds first-party preference rule on the writer side | n/a |
| SIE | None | n/a |

## 4. Acceptance Criteria — Cross-Cutting

A run is **content-quality compliant** under this PRD when all of the following hold:

1. The brief output's `metadata.semantic_dedup_collapses_count + definitional_restatements_discarded_count ≥ 0` (i.e., the new fields exist; non-zero values are expected when the candidate pool actually contained semantic duplicates).
2. The brief output's `discarded_headings[].discard_reason` enum includes `semantic_duplicate_of_higher_priority_h2`, `definitional_restatement`, `too_short_after_sanitization`, and `non_descriptive_after_sanitization` (i.e., the new reasons are wired up).
3. The brief output's `spin_off_articles[]` field is present (may be empty; legacy `silo_candidates[]` is also present until v1.9).
4. The writer output's `article[]` contains exactly one section each of `type: "key-takeaways"`, `type: "intro"`, `type: "cta"`, in addition to the existing content/faq/conclusion sections.
5. The writer output's metadata contains `paragraph_length_violations: []`, `under_cited_sections: []`, `topic_brand_alignment: "brand_aligned"|"brand_agnostic"`, `dropped_for_low_topic_adherence: []`, and `brand_mention_count: int`.
6. No body paragraph in any section exceeds 4 sentences (or, if it does, the violation is recorded in `paragraph_length_violations`).
7. No two H2 headings have cosine similarity ≥ 0.85.
8. Headings show no SERP-artifact patterns from the R2 sanitization table.
9. At least 50% of citable claims (per R7 detection rules) in every content section are followed by a `{{cit_id}}` marker, or the deficit is recorded in `under_cited_sections`.

## 5. Out of Scope (v1.0 of this PRD)

- LLM-based contextual heading dedup (current scope is embedding-similarity based; LLM "do these mean the same thing?" check is a v1.1 candidate if embedding dedup misses persist).
- Multi-paragraph "Quote Card" / "Definition Card" structural blocks beyond Key Takeaways. Schema is open for v2 additions.
- Image-aware brand mentions (logo placement, alt-text brand inclusion).
- Style guide enforcement beyond the brand voice card (Oxford comma, em-dash style, sentence-case vs. title-case headings) — see frontend `toTitleCase` for the title-case rendering decision; this PRD does not prescribe sentence vs. title case at generation time.
- Reading-level scoring (Flesch-Kincaid) — paragraph length is the sole readability metric in v1.0.
- Auto-generated brand asset URLs (the brand voice card's `client_services` strings are not URL-resolved in v1.0).

## 6. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-05-01 | Initial draft. Authored in response to the 2026-05-01 audit of the `tiktok shop` run. Encodes R1–R7. |
