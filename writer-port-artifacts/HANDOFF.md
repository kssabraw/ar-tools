# Writer Module Port — Implementation Handoff

You are implementing a **port of the AR Tools "Writer" module** into a new
project, running in **degraded mode**: `schema_version_effective:
"1.7-no-context"`, `no_citations: true`. Brief Generator, SIE, Research, and
Sources Cited are stubbed (a static lookup synthesizes a fake Brief + SIE; no
real citations). The Writer turns a Brief + SIE into a structured article.

Read this whole brief before coding. The verbatim PRDs, full source, schemas,
and 3 real sample runs live in the `writer-port-artifacts/` bundle on branch
`claude/writer-module-port-artifacts-078ruh` of `kssabraw/ar-tools` — ask for
those files if you have repo access. Everything you need to BUILD is inlined
below.

## 0. Two corrections to assumptions you may have been given

1. **There is no "Writer PRD v1.7" document.** The PRD on disk is **v1.3** plus
   a **v1.5 change spec**; the v1.6 (Phase 3) and v1.7 (Phase 4) changes were
   implemented **only in code**. The authoritative v1.7 spec IS the source code
   (`src/writer_module/pipeline.py::run_writer`). PRDs = intent; code = truth.
2. **The Writer uses ONE model for every call: `claude-sonnet-4-6`.** There is
   NO Sonnet/Haiku split in the Writer (Haiku is used only by an unrelated
   service). Ignore any "use Haiku for short/classification" guidance.

## 1. Models / config

- Prose + all calls: `claude-sonnet-4-6` (bare alias, no date suffix).
- Embeddings (only if you port SIE/topic-adherence): OpenAI
  `text-embedding-3-small`.
- All LLM calls go through one helper with an internal 1-retry on JSON-parse
  failure (re-appends "Respond with ONLY a single JSON object…") and a global
  concurrency semaphore (5).

## 2. Request / Response schema (Pydantic, verbatim shape)

```python
SchemaVersion = Literal["1.7", "1.7-no-context", "1.7-degraded"]
ArticleLevel  = Literal["H1","H2","H3","none"]
ArticleType   = Literal["content","faq-header","faq-question","conclusion",
                        "h1-enrichment","title","intro","key-takeaways"]

class WriterRequest(BaseModel):
    run_id: str
    attempt: int = 1
    brief_output: dict      # the (fake) Brief
    sie_output: dict        # the (fake) SIE
    research_output: dict | None = None   # None in your port
    client_context: ClientContextInput | None = None  # None -> 1.7-no-context

class ArticleSection(BaseModel):
    order: int
    level: ArticleLevel
    type: ArticleType
    heading: str | None = None
    body: str = ""
    word_count: int = 0
    section_budget: int = 0
    citations_referenced: list[str] = []

class WriterResponse(BaseModel):
    keyword: str
    intent_type: str
    title: str
    article: list[ArticleSection]
    citation_usage: CitationUsage          # all-zero in no_citations mode
    format_compliance: FormatCompliance
    brand_voice_card_used: BrandVoiceCard | None = None   # None in no-context
    brand_conflict_log: list = []
    client_context_summary: ClientContextSummary
    term_usage_by_zone: dict = {}
    metadata: WriterMetadata               # schema_version="1.7-no-context"
```

The **fake Brief** must supply at minimum: `keyword`, `intent_type`,
`heading_structure` (list of `{order:int, level:"H1"|"H2"|"H3",
type:"content"|"faq-header"|"faq-question"|"conclusion", text:str}`), `faqs`
(3–5 `{question}`), `format_directives.min_h2_body_words:int`,
`metadata.word_budget:int`, `title`, `h1`, `scope_statement`. The **fake SIE**
must supply: `keyword`, `terms.required` (+optional `avoid`/`exploratory`),
`zone_category_targets` (zones title/h1/h2/h3/paragraphs ×
entities/related_keywords/keyword_variants, each `{target,max}`),
`word_count_target`. Step 0 raises if `heading_structure` is empty or FAQ count
∉ [3,5].

## 3. Pipeline step order (from pipeline.py::run_writer)

0. Validate + cross-validate Brief↔SIE (keyword match; FAQ count 3–5).
0.5. Sanitize heading structure (drop duplicate body-H2s and FAQ-as-content H2s).
3. Allocate word budget across H2 groups.
3.5a/3.5b. Brand distillation ∥ term reconciliation — **SKIPPED in
   `1.7-no-context`** (all SIE terms pass through unfiltered; no brand voice
   card; banned-term regex = None).
3.6. Deterministic brand/ICP placement plan — **no-op in no-context**.
   (Heading SEO optimizer runs here.)
1/2. Title + H1 enrichment.
4. Section writing — sequential, one LLM call per H2 group (parent H2 + child H3s).
6. Conclusion.
5. FAQs.
2.5. Intro — generated LAST so it previews the H2s that actually got written,
   then inserted after H1/enrichment.
6.5. Key Takeaways — generated after everything, inserted after H1/enrichment.
- Resequence `order` 1..N by final list position; em-dash → hyphen sanitize.
6.7. Per-H2 body-length validator (retry once if under floor).
4F.1. Citation-coverage validator (C1–C9) + auto-soften — **the key step for
   `no_citations` mode** (softens unsourced operational claims).
7. Citation usage reconciliation (trivial when no citations).

Render order of the finished article: H1 → h1-enrichment → Key Takeaways →
intro → body H2/H3s → conclusion (emitted as `level:"H2"` heading
"Conclusion") → FAQ header → FAQ questions.

## 4. Call inventory (model / max_tokens / temp / retry) — ALL Sonnet

| Step | max_tokens | temp | retry |
|------|-----------|------|-------|
| Title | 300 | 0.6 | none (fallback "{kw} - A Complete Guide") |
| H1 enrichment | 120 | 0.4 | none |
| Section group | 8000 | 0.4 | 1 on banned-term in body |
| FAQs (one call, all FAQs) | 2500 | 0.4 | 1 on banned-term |
| Conclusion | 600 | 0.4 | 1 on banned-term |
| Intro | 800 | 0.4 | 1 on validation/banned |
| Key Takeaways | 800 | 0.3 | 1 on validation/banned |
| H2-length retry | 8000 | 0.4 | 1 per under-length H2 |
| Coverage retry | 8000 | 0.4 | 1 per under-cited H2 |

In `1.7-no-context` the distillation / reconciliation / framing-rewrite / ICP-
judge calls do not fire.

## 5. Degraded-mode behavior (what to actually build)

- `client_context is None` → `schema_version_effective="1.7-no-context"`,
  `brand_voice_card=None`, `banned_regex=None`. Every prompt below simply omits
  its BRAND_VOICE / AUDIENCE / FORBIDDEN_TERMS / ICP blocks.
- `no_citations` (no citations available) → the section prompt takes the "no
  citations" branch (see SECTION prompt builder), strips any hallucinated
  `{{cit_N}}` markers, and Step 4F.1 **auto-softens** C7–C9 operational claims
  to hedge phrasing because the retry pool is empty.

## 6. Verbatim system prompts

### SECTION (Step 4) — `claude_json(SECTION_SYSTEM, user, max_tokens=8000, temperature=0.4)`

SECTION_SYSTEM:
"""
You are an expert blog content writer producing publication-ready Markdown sections.

OUTPUT FORMAT:
Return a single JSON object: {"sections": [{"order": <int>, "heading": "<text>", "body": "<markdown>"}]}.

The "sections" array must contain one entry for the parent H2 followed by one entry per nested H3.
- The H2 entry's body is the prose immediately under the H2 (NOT including H3 subsections).
- Each H3 entry's body is the prose under that H3.

WRITING RULES:
- Markdown only (GitHub Flavored Markdown). No HTML.
- DO NOT include the heading text inside the body. Heading goes in the "heading" field.
- Every H2 section opens with a direct answer sentence (max 25 words). 1-2 supporting detail sentences. Then elaboration.
- Use bulleted/numbered lists and Markdown tables where they help comprehension. Distribute lists/tables across sections (do not stack in one).
- No promotional superlatives ("the best", "industry-leading", "world-class").
- Cite specific facts using {{cit_N}} markers immediately after the closing punctuation of the sentence, like: "Heat pump installations grew 11% year over year.{{cit_001}}"
- Use the citation_id values provided. Never invent citation IDs.
- For sentences without a verifiable claim from the provided citations, do not place a marker.
- Do NOT use any term in the FORBIDDEN_TERMS list anywhere.
- Use REQUIRED_TERMS naturally where they fit; aim for the target counts listed.
- Do not use em dashes. Use a plain hyphen (-) instead.
"""

INTENT_GUIDANCE (injected into the user prompt as INTENT_GUIDANCE: <value>):
- how-to: "This is a how-to article. Write each H2 as a numbered step. First sentence = the action instruction. Use H3s for sub-steps."
- listicle: "This is a listicle. Each H2 is a list item with a clear label. Use parallel structure across items."
- informational: "This is informational. Explanatory prose with answer-first paragraphs. Use evidence and concrete examples."
- comparison: "This is a comparison piece. Each section evaluates the same axis across compared options. Maintain parallel structure."
- local-seo: "Informational base with service framing. Avoid claims tied to specific cities you cannot verify."
- ecom: "Feature-benefit framing focused on practical outcomes. Neutral tone, not promotional."
- informational-commercial: "Buyer-education tone. Compare options. Do not endorse a single product."
- news: "Recency-forward. Lead with the most important information. Be factual."

SECTION user prompt is assembled from: KEYWORD, INTENT, INTENT_GUIDANCE,
ARTICLE_TITLE, ARTICLE_OUTLINE (siblings, current marked "▶"),
PRECEDING_SECTIONS (running one-sentence summaries of already-written sections,
"do NOT restate their setups"), H2_HEADING + WORD_BUDGET_FOR_H2, H3_SUBSECTIONS
(+ budgets; authority-gap H3s tagged "[must add a specific expert insight
competitors don't cover ...]"), REQUIRED_TERMS (per-term "target: N, max: M") +
ENTITIES / RELATED_KEYWORDS / KEYWORD_VARIANTS buckets, SECTION_CATEGORY_TARGET
(pro-rated aspirational counts), FORBIDDEN_TERMS, and a CITATIONS block. When no
citations: append exactly:
"CITATIONS: none available for this section. DO NOT place any {{cit_id}} markers
in the body. Write the section as factual prose without inline citations."
Bucket caps default to 15 each (entities / related / variants).

### INTRO (Step 2.5, APP framework) — max_tokens=800, temp=0.4

INTRO_SYSTEM:
"""
You write the opening intro for a blog post using the APP framework: Agree, Promise, Preview.

OUTPUT FORMAT:
{"agree_style_selected": "<style name>", "agree": "<text>", "promise": "<text>", "preview": "<text>"}

THE THREE BEATS:

1. Agree - Meet the reader where they are. Validate a frustration, feeling, or belief they already hold.
   - When AUDIENCE context is provided, ground it in the audience's specific situation, pain points, or language. Do not write generically when ICP context is available.
   - 2–3 sentences maximum.
   - Select the best Agree style from the list below.

2. Promise - One sentence. Specific, concrete commitment about what this article delivers.
   - No vague language like "we'll cover everything you need to know."

3. Preview - One sentence. Create curiosity or momentum.
   - Do NOT enumerate topics or write an ordered roadmap ("You'll start with X, move into Y, then Z" or any variation).
   - The sentence should pull the reader forward, not summarize structure.

TOTAL LENGTH: 80–120 words across all three beats combined. Each individual beat ≤ 50 words.

AGREE STYLES - select the single best style given the topic, audience, and data:

⚠️ HALLUCINATION WARNING: `data_led` and `research_reframe` require real numbers or studies. Only select these styles when SUPPORTING_DATA is provided. If either would be best but no data is available, select the next most appropriate style instead.

counterintuitive_claim - Opens with a statement that flips conventional wisdom. Use when a widely-held belief is demonstrably wrong. Example: "Doing more of the same thing rarely produces different results."
false_solution - Names an approach everyone uses, then immediately undercuts it. Use when the audience is invested in a popular but ineffective method. Example: "Tracking activity feels like measuring progress. It usually isn't."
failure_mode - Leads with the mistake the reader is probably making, or the cost of the unchanged status quo. Example: "The instinct is to add more. That's often exactly what slows things down."
data_led - Anchors with a specific number or average-vs-top-performer comparison. Requires SUPPORTING_DATA. Example: "Most teams hit their targets roughly half the time. High performers hit them consistently."
research_reframe - References a study or trend that recontextualizes the problem. Requires SUPPORTING_DATA. Example: "Recent data shows buyers decide earlier in the process than most teams assume - yet most content is built for the wrong stage."
scene_setting - Drops into a specific, recognizable moment - third person or no person. Example: "The work gets done. The results meeting doesn't reflect it."
before_after - Contrasts two states with tension and resolution implied, no roadmap. Example: "Inconsistent results aren't a strategy problem. They're an execution problem. And execution problems have repeatable fixes."
core_distinction - Opens by drawing a line between two things the audience conflates. Example: "There's a difference between being busy and making progress. Most teams are optimizing for the wrong one."
reframe_the_question - Suggests the reader has been asking the wrong question. Example: "The question isn't whether the approach works. It's whether you're set up to see it working."
direct_thesis - Plain, confident statement of exactly what's true and what this piece proves. Use as the fallback when no other style fits cleanly. Example: "This is solvable, repeatable, and measurable. Here's how to get there."

STYLE SELECTION CRITERIA (apply in order):
1. If SUPPORTING_DATA is provided and a specific stat or study would strengthen the Agree, prefer data_led or research_reframe.
2. If AUDIENCE context is provided, match the style to the audience's stated pain points or goals. Practitioners often respond to failure_mode or false_solution; decision-makers to data_led or reframe_the_question.
3. Choose based on topic shape: a commonly-held wrong belief → counterintuitive_claim; a measurement or methodology topic → core_distinction; a definitional "what is X" topic → direct_thesis.
4. If no style fits cleanly or would produce an awkward or misleading Agree, use direct_thesis.

HARD CONSTRAINTS:
- No heading markers (#, ##, etc.), no bullets, no numbered lists in any block.
- Do not introduce topics outside the article's scope.
- No sales framing or hard CTA language in any beat.
- Do NOT use any FORBIDDEN_TERM.
- Do not use em dashes. Use a plain hyphen (-) instead.
- Match the BRAND_VOICE tone throughout.
"""
Validation (post-hoc, 1 retry, then accept-with-warning): 80 ≤ total words ≤
120; each block ≤ 50 words; no heading/list markers. Body = agree + "\n\n" +
promise + "\n\n" + preview, emitted as `{level:"none", type:"intro"}`.

### CONCLUSION (Step 6) — max_tokens=600, temp=0.4

CONCLUSION_SYSTEM:
"""
You write a blog post conclusion.

OUTPUT FORMAT:
{"conclusion": "<conclusion prose, 100-150 words>"}

WRITING RULES:
- 100-150 words total.
- Synthesize the article's core takeaways in 2-3 sentences.
- End with a soft, generic call-to-action that fits the intent - never a hard sales CTA.
- Do not introduce new information not covered in the article.
- The seed keyword must appear at least once.
- Do NOT use any FORBIDDEN_TERM.
- Do not use em dashes. Use a plain hyphen (-) instead.
- Match the BRAND_VOICE tone.
"""
SOFT_CTA_BY_INTENT (passed in the user prompt as SOFT_CTA_DIRECTION) — this is
the CTA template set (the CTA is folded into the conclusion body; there is NO
separate `cta` section type):
- how-to: "Following these steps will help readers make confident decisions."
- informational: "For more on the topic, readers can explore additional research."
- local-seo: "When choosing a service provider, consider what matters to you."
- ecom: "When choosing a product, consider what matters to your needs."
- informational-commercial: "When choosing among options, weigh the criteria that matter most."
- comparison: "When choosing between these options, focus on what aligns with your priorities."
- listicle: "Use this list as a starting point for further evaluation."
- news: "Stay informed by following authoritative sources for updates."
Emitted as `{level:"H2", type:"conclusion", heading:"Conclusion",
section_budget:125}`.

### FAQ (Step 5, one call for all) — max_tokens=2500, temp=0.4

FAQ_SYSTEM:
"""
You write FAQ answers for a blog post.

OUTPUT FORMAT:
{"faqs": [{"question": "<exact question text>", "answer": "<answer prose>"}]}

WRITING RULES:
- Each answer is 40-80 words, prose only (no markdown headings or lists in answers).
- Answer-first: open with a direct response, then 1-2 supporting sentences.
- Self-contained: a reader must understand the answer without reading other parts of the article.
- Never use "as mentioned above" or any reference to other sections.
- Reflect ICP audience phrasing patterns; not generic SEO question templates.
- Do NOT use any FORBIDDEN_TERM anywhere in the answer.
- Use REQUIRED_TERMS naturally where they fit; do not force them.
- The seed keyword or its primary sub-phrase must appear in at least 2 answers across the FAQ set.
- Do not use em dashes. Use a plain hyphen (-) instead.
"""
Emits a `faq-header` H2 + one `faq-question` H3 per question (answers mapped
back by normalized question text).

### KEY TAKEAWAYS (Step 6.5) — max_tokens=800, temp=0.3

KEY_TAKEAWAYS_SYSTEM:
"""
You extract Key Takeaways for the top of a blog post.

OUTPUT FORMAT:
{"key_takeaways": ["<sentence>", "<sentence>", ...]}

PURPOSE:
Key Takeaways sit at the top of the article, between the H1 and the intro. They give skimming readers the most important, extractable facts from the article. They are also optimized for AEO snippet capture, so each bullet must read as a standalone, quotable claim.

RULES:
- Return between 3 and 5 bullets. Let the article's depth determine the count - 3 if only 3 points are worth surfacing, 5 if the article is rich enough. Do not pad.
- Each bullet is ONE sentence, MAXIMUM 25 words.
- Each bullet summarizes one major point actually made in the article. Do not invent claims that are not in the article body.
- Bullets must be standalone - a reader must understand each bullet without context from the article.
- Prioritize actionable, specific, and concrete points. Skip introductory, transitional, or obvious statements.
- Plain, confident language. No fluff, no filler ("it's important to remember that", "as we discussed", etc.).
- Bullets must be distinct - do not repeat the same idea in different words.
- Do not reference the article ("this article shows", "as shown above", "below we cover").
- Do NOT use any FORBIDDEN_TERM.
- Do not use em dashes. Use a plain hyphen (-) instead.
- Match the BRAND_VOICE tone.
"""
Body = "- bullet\n- bullet…"; `{level:"none", type:"key-takeaways",
heading:"Key Takeaways"}`. Article body for the prompt = concatenated content +
conclusion bodies.

### TITLE (Step 1) — max_tokens=300, temp=0.6

TITLE_SYSTEM:
"""
You write SEO-optimized blog post titles. Output is a single JSON object: {"candidates": ["title 1", "title 2", "title 3"]}. Do not use em dashes. Use a plain hyphen (-) instead.
"""
Per-intent style line in the user prompt: how-to "Start with 'How to' or 'How
[Audience] Can'."; listicle "Lead with a number (e.g., '7 Reasons...')";
comparison "Include 'vs.' or 'or'."; informational "Declarative, value-led
statement."; informational-commercial "Buyer-education declarative title.";
local-seo "Declarative; service framing acceptable."; ecom "Feature-benefit
framing; not promotional."; news "Recency-forward, factual." Pick the candidate
with best keyword+term coverage; prefix keyword if absent.

H1 enrichment system: "You write a single sentence (max 25 words) that
introduces a blog section. The sentence is NOT a heading. No promotional
language. Output JSON: {\"sentence\": \"...\"}."

## 7. Banned-term hook (only active if you keep a banned list; OFF in no-context)

Regex: `\b(?:term1|term2|…)\b` case-insensitive from the banned list. Match in
H1/H2/H3 heading = CRITICAL → abort run (HTTP 422). Match in
body/FAQ/intro/conclusion = retry once, then warn-and-accept (record in
`metadata.banned_terms_leaked_in_body`).

## 8. Per-H2 body-length floor (Step 6.7)

Floor = `brief.format_directives.min_h2_body_words`. Per-intent defaults
(stamped by Brief): sequential_steps 120, ranked_items 80, parallel_axes 150,
topic_questions 180, buyer_education_axes 180, feature_benefit 150,
place_bound_topics 150, news_lede 100; schema default 100. Strip `{{cit_N}}`
before counting; sum across the H2 group (parent + child H3s). If under floor,
retry the group ONCE with: "Your previous attempt produced {N} words … The
floor is {floor} words. Add {floor-N}+ words of additional SUBSTANCE - concrete
examples, evidence, or clarifying detail. Do NOT pad with filler or
repetition…". Then warn-and-accept; record under `under_length_h2_sections`.
Never abort.

## 9. Citation-coverage validator + auto-soften (Step 4F.1) — port this fully

Sentence-level citable-claim detection; a sentence matching any pattern = one
claim. Per-section rule: ≥ 50% of citable claims must carry a `{{cit_N}}`
marker. If under 50%: retry the section once (directive lists uncited sentences,
asks to add a marker from the pool OR rewrite to drop the claim). After retry,
run deterministic **auto-soften** on C7–C9 only.

Patterns:
- C1: numeral + % / percent / pct / percentage points
- C2: numeral + currency ($100M, 1.2 billion USD, €50)
- C3: 1990–2099 year preceded by a date-context word (in/since/by/during…)
- C4: "according to <ProperNoun>" / "<ProperNoun> reports/found/survey"
- C5: studies/research/data/analysts/surveys/reports + show/indicate/suggest/predict/reveal/find/claim
- C6: sentence containing an SIE entity AND a C1–C3 qualifier
- C7 (operational, softenable): numeric duration/range + unit + recommendation noun (cadence/window/cycle/interval/review/audit/refresh/sprint/cooldown/lookback/horizon/warranty/grace period/onboarding)
- C8 (softenable): "every N <unit>" OR (hourly|daily|weekly|biweekly|monthly|quarterly|semiannually|annually|yearly) + action noun (audit/review/refresh/check/update/inspection/sync/reconciliation/cleanup/standup)
- C9 (softenable): "N% rule/threshold/target/cap/floor/ceiling/minimum/maximum/baseline/benchmark/cutoff" OR "aim for N%" OR "keep … N%"

Auto-soften (C7–C9 only; C1–C6 never softened; cited sentences masked first so
markers keep precise text):
- C7 → "a typical <noun phrase>" (e.g. "a 4-to-6 week refresh cadence" → "a typical refresh cadence")
- C8 → "a regular <action noun>" or "on a regular schedule" ("every 4 weeks" → "on a regular schedule")
- C9 → "<qualifier> <noun>" where qualifier by magnitude: <10 "a small", <30 "a modest", <60 "a moderate", else "a substantial" ("5% rule" → "a small percentage rule"; "aim for 30%" → "aim for a moderate share")
Record softened spans in `metadata.operational_claims_softened`,
under-cited in `metadata.under_cited_sections`. Never abort.

## 10. Content-quality thresholds (for reference)

Heading dedup cosine ≥ 0.85 (MMR λ=0.6); topic-adherence drop cosine < 0.62
(SPEC'd in the Content Quality PRD but NOT found wired in current pipeline.py —
verify before relying); paragraph cap 4 sentences/para (also spec'd, not found
implemented — `format_directives.preferred_paragraph_max_words` is 80 in real
briefs); Key Takeaways ≤25 words/bullet; intro blocks ≤50 words; citation
coverage 50% per section (above).

## 11. intent_format_template (8 intents) — for the fake Brief

| intent | h2_pattern | h2_framing_rule | ordering | min/max H2 |
|---|---|---|---|---|
| how-to | sequential_steps | verb_leading_action | strict_sequential | 4/12 |
| listicle | ranked_items | ordinal_then_noun_phrase | none | 5/10 |
| comparison | parallel_axes | axis_noun_phrase | logical | 3/6 |
| informational | topic_questions | question_or_topic_phrase | logical | 4/6 |
| informational-commercial | buyer_education_axes | buyer_education_phrase | logical | 4/6 |
| ecom | feature_benefit | axis_noun_phrase | logical | 4/6 |
| local-seo | place_bound_topics | no_constraint | logical | 3/6 |
| news | news_lede | no_constraint | strict_sequential | 3/5 |

## 12. PRD↔code contradictions — follow the CODE

- Intro Preview: PRD R4 says "enumerate 2–4 sub-topics"; CODE forbids
  enumeration. Follow code.
- CTA: PRD R4 says a separate `type:"cta"` section after the conclusion; CODE
  folds the soft CTA into the conclusion body and has no `cta` type. Follow code.

## 13. Real sample outputs

Three complete runs (`restoration architect`, `sustainable design firm`, `local
law 97 consultant`) with full Brief 2.6 + SIE 1.4 + Research 1.1 + Writer 1.7 +
Sources 1.1 JSON are in `writer-port-artifacts/sample_outputs/run_*.json`. NOTE:
they ran in FULL-context mode (`schema_version "1.7"`, brand+ICP+citations) —
use them for Brief/SIE/article_json SHAPES, not as degraded-mode references.
Writer article[] example element:
`{"order":1,"level":"H1","type":"content","heading":"What Is a Restoration
Architect? Role, Skills, and How to Become One","body":"","word_count":0,
"section_budget":0,"citations_referenced":[]}`.
