# Brand Guide Generator — Module PRD v1.0

**Status:** Proposed (not built). Draft for review + adversarial review.
**Owner decisions captured:** 2026-09-15 (see §2).
**Author context:** Seeded by a review of a Google Pomelli "Brand Book" export for Nova Life Peptides; the goal is a brand guide that is *more complete and in-depth* than that thin, visual-only deliverable, grounded in the suite's existing client assets.
**Design-review amendments (2026-09-15):** a Rounds 1–4 design grill refined this PRD — purpose primacy + render profiles (§1 / §2 D1), visual extraction reclassified as best-effort *garnish* (§5.1), **D4 reversed to no headless browser** (§2 D4 / §4.1 / §8), enforcement-refresh downgraded to suggest-only (§4.8), a structured-field correction path (§9), and a flag-gated regulated guardrail with an explicitly accepted residual risk (§5.3). All §12 open questions are now **Resolved**.

> This document is the product/behaviour authority for the Brand Guide module. It reuses existing suite infrastructure wherever possible; §7 is the verified reuse map (grounded in a read-only inventory of the live code, 2026-09-15). Where this doc and a shared service disagree on *how* a thing works, the code wins and this doc is wrong — flag it.

---

## 1. What this is

A per-client tool that turns **a website URL + the client's existing ICP/differentiators/brand-voice assets** into a polished, in-depth **Brand Guide** — delivered as both:

1. a **client-facing PDF** (the deliverable; a soft sales asset — "here's your brand, here's where it's leaking, here's the system going forward"), and
2. a **structured, versioned record** that can *refresh* the suite's existing enforcement assets (`clients.brand_voice`, the Voice & Audience Card) so the guide isn't just a document — it tightens content generation.

**Primacy (design review).** The three jobs are ranked: **(1)** an internal **agency working document** — the agency *presents* it, never hands it over raw; **(2)** a **client-presentable export** — the same document with audit findings reframed as forward-looking opportunities (§4.7); **(3)** **enforcement-refresh** — suggest-only in v1 (§4.8). The **PDF deliverable is the headline**; the measured visual layer is **best-effort garnish** (§5.1) over the voice/ICP/differentiator assets that are the real moat.

It is a **Brand Audit + Brand Guide** in one: every visual and voice section carries a **Documented** layer ("your brand as it exists today", extracted from the live site) and a **Proposed** layer ("the professional system going forward", with usage rules, a real type scale, imagery direction, worked voice examples, and explicitly flagged gaps).

### 1.1 Why the Pomelli reference is thin (the bar to clear)

The Pomelli export was 7 pages: cover, a one-paragraph overview + tagline, logo geometry (clear space / min size), one typeface, a 4-color palette, an empty imagery page, and a brand-voice *adjective list*. Its gaps — which this module closes — were:

- It documents *what* the marks are, never *how to use them* (no do/don't, no color usage ratios, no accessible pairings, no type scale).
- Brand voice is a word cloud with **zero worked examples** (no "we say / we don't", no sample headline/CTA/blurb).
- **No audience** at all — exactly where the suite's ICP + differentiators make it far richer.
- **No messaging layer** — no positioning statement, value proposition, key messages, or boilerplate (the parts a team actually reuses).
- Imagery is a vibe, not a rule.
- Nothing is grounded in evidence — generic AI descriptors ("Bio-Futuristic Sharpness") untied to the real site, products, or customers.

The suite already owns the two halves Pomelli is weakest at (real brand *voice* with enforceable terms; real *audience* via ICP + differentiators). The opportunity is fusing **measured visual identity (from the live site)** + **a read of the brand's aesthetic/feel (vision over the real render)** + **existing voice/ICP assets** + **a synthesized messaging + imagery layer** into one deep document.

---

## 2. Locked owner decisions (2026-09-15)

| # | Decision | Choice | Implication |
|---|----------|--------|-------------|
| D1 | **Purpose** | **Both**, but **ranked**: (1) internal agency working doc → (2) client-presentable export → (3) enforcement-refresh | One generator, a `profile: internal\|client` render flag (§4.7). The PDF is the headline; enforcement-refresh is **suggest-only in v1** (§4.8), not a co-equal auto-write. |
| D2 | **Mode** | **Both** — "extensive documentation *and* in-depth professional proposals" | Every section is dual-layer (Documented + Proposed), with a gap analysis. This is an audit+guide, not a pure documentation tool. |
| D3 | **Creative license** | **Grounded synthesis** | The LLM may invent swatch names, taglines, aesthetic/imagery direction — but **NEVER** a product claim, efficacy, dosage, regulatory status, or any fact (a **universal** prompt rule for every client). For clients with the manual **`regulated`** flag set, a deterministic input-filter + a pre-render sign-off gate additionally engage. See §5.3. |
| D4 | **Visual extraction** | **No headless browser** — exact declared hex from **scraped CSS** (ScrapeOwl `render_js`), ranked by **screenshot-pixel dominance** (Pillow over the DataForSEO `page_screenshot`) | **Reverses the original "Browserless over CDP" choice** (design review): visual extraction is a *garnish* layer (§5.1), so true computed styles don't justify a browser — and pixel-dominance over the rendered screenshot is a truer "what dominates the page" signal anyway, while the census machinery wasn't reusable as-is regardless. No Chromium in any image, no Browserless vendor, no new key, no client-URL egress to a third party; reuses only existing paid paths (ScrapeOwl, DataForSEO screenshot) + an existing dep (Pillow). See §4.1 + §8. |

**Design-review resolutions (2026-09-15, Rounds 1–4):** all six §12 open questions are now resolved — each carries its **Resolved** answer in §12. Primacy + render profiles (D1), garnish framing (§5.1), the no-browser reversal (D4), suggest-only enforcement (§4.8), the structured-field edit path (§9), and the flag-gated guardrail + accepted residual risk (§5.3) are settled.

---

## 3. The deliverable — section structure

The generated guide has these sections. Each is marked by its dominant **source** and whether it carries a Documented/Proposed split. "🆕" = requires the new live-site extraction; everything else is assembly over existing data.

| # | Section | Documented layer (from) | Proposed layer (synthesized) |
|---|---------|-------------------------|------------------------------|
| 0 | **Cover** | Client name, logo | Tagline |
| 1 | **Brand Foundation** | Overview paragraph, values (`brand_voice`), differentiators | Mission/promise, positioning statement, tagline + rationale |
| 2 | **Audience (ICP)** ⭐ | Primary + secondary segments, demographics, triggers, fears, motivations, hooks, trust signals (`detected_icp`) | "What they need to hear" framing, objection handling |
| 3 | **Voice & Messaging** ⭐ | Personality (3 traits), tone, current sample phrases (`brand_voice`), must-use / never-use vocabulary (Voice Card) | Tone-by-context matrix, **worked examples** (headline, CTA, product blurb, email opener), we-say/we-don't table, key messages, boilerplate (short + long) |
| 4 | **Logo** | Extracted logo candidates (🆕) or `logo_url`/GBP | Clear space, min size (deterministic rules), do/don't usage guidance |
| 5 | **Aesthetic & Art Direction** ⭐🆕 | The *felt* vibe read off the real screenshots (§4.3): aesthetic descriptors + evidence, mood-axis placements (minimal↔maximal, warm↔clinical, premium↔budget, …), color/type/shape/density/imagery character | Named aesthetic direction + rationale, **coherence check** (does the executed detail match the intended feel? gaps flagged), "keep doing / dial up / dial back" |
| 6 | **Color** 🆕 | Real palette: named swatches + Hex/RGB/CMYK/HSL, area-weighted dominance | Organized roles (primary/secondary/neutral), 60/30/10 usage ratios, accessible pairings (WCAG contrast), do/don't, **gaps flagged** (e.g. "11 near-duplicate grays → consolidate to 3") |
| 7 | **Typography** 🆕 | Real typefaces + measured type sizes/weights | Named type scale (H1→caption with size/weight/line-height), pairing rules, fallback stacks |
| 8 | **Imagery & Iconography** ⭐ | Observed imagery (from the render/screenshot, described) + its treatment from the vibe read | Subject/lighting/treatment direction, do/don't, stock-vs-custom guidance, iconography style |
| 9 | **Applications** (optional, v1.1) | — | Mockups: website hero, social post, business card, letterhead, label (reuse Website-Builder theme render) |
| 10 | **Brand-in-action** | — | Quick cheat sheet, "who owns brand questions", change log/version |

⭐ = the sections that decisively out-depth Pomelli and lean on data the suite already owns.

---

## 4. Pipeline

Eight stages. Stages 1–3 (capture, deterministic extract, aesthetic/vibe read) are the new capability; the rest is assembly + reuse.

### 4.1 Capture (no headless browser — D4) 🆕

Capture the homepage (the **visual authority**) + up to 2 auto-discovered key pages (a product/service + an about/contact, discovered from nav — §12 Q2). **No headless browser:**

- **Rendered HTML** via the existing production **ScrapeOwl** path (`scrapeowl_fetch(url, render_js=True)`) — for CSS declarations (`color`/`background-color`, `font-family`, `font-size`, `fonts.googleapis.com` hrefs) and the DOM (logo/nav discovery, site copy).
- **Screenshot** via the existing **DataForSEO `page_screenshot`** path (the same one `qa_visual` uses — fractions of a cent, no Chromium) — for the palette pixel-dominance step (§4.2) and the vibe read (§4.3).
- The **homepage is the sole source for palette/fonts/type/vibe**; the +2 pages feed **logo candidates, imagery variety, and a consistency check only — never the palette census** (so a product page's photography can't pollute the brand palette). Page scope is operator-overridable.
- Best-effort + bounded (per-page timeout, page cap). A dead page adds a degraded note; the guide still generates from whatever was captured.

### 4.2 Extract (deterministic, no LLM) 🆕

Turn the scraped CSS + screenshot into a **visual census** (pure Python, unit-testable):

- **Colors** — **exact declared hex** parsed from the scraped CSS declarations (`color`/`background-color`), **ranked/weighted by screenshot-pixel dominance** (Pillow quantization over the DataForSEO screenshot — a truer "what dominates the rendered page" signal than source frequency, and it needs no browser); **cluster near-duplicates** (Euclidean RGB distance ≤ tolerance) into representatives with a dominance `share`; emit Hex + RGB + HSL (CMYK computed for print). Drop transparent/near-transparent. *(Exact hex comes from the CSS so JPEG/anti-alias drift never touches the reported numbers; the screenshot only ranks which colors matter.)*
- **Fonts** — first family in each `font-family` stack from the scraped CSS, frequency-weighted → primary/secondary families; cross-reference `fonts.googleapis.com` hrefs for the canonical family names + weights.
- **Type scale** — distinct declared `font-size` px values from the scraped CSS, frequency-weighted, sorted → the real hierarchy (declared, not cascade-computed — sufficient for the garnish layer).
- **Weights / radii / spacing** — frequency tables.
- **Logo candidates** — ranked: `og:image`, `<img>` with "logo" in src/alt/class, header/home-link image, favicon.

> **Prototype validation (2026-09-15):** the extractor logic, run against a representative fixture, recovered a full palette (including the four colors a human brand book named by hand), both fonts, a 7-step type scale, weights, radii, and 4 logo candidates. **Census reuse is a salvage, not a drop-in:** `website_theme_precompile.py`'s `census_styles`/`TokenCensus` are count-only and hard-wired to the Claude-Design *upload* format (regex over inline `style=`), with no per-item weight seam — so this is a **new weight-aware census** that salvages the color/font normalization (~25 lines), fed from scraped CSS + screenshot-pixel dominance rather than computed styles. **Live-site capture uses the existing ScrapeOwl + DataForSEO paths, no browser** (§4.1 / §8); live runs are blocked in the Claude Code sandbox by egress policy (same limitation as DataForSEO/nlp) and are verified on the deployed worker.

### 4.3 Aesthetic & Vibe read (vision over the screenshots) 🆕

The deterministic census (§4.2) captures the *ingredients* of the visual identity — exact colors, fonts, sizes, radii — but not the **aesthetic**: the gestalt a human feels in two seconds (minimal↔maximal, warm↔clinical, playful↔serious, budget↔premium, organic↔geometric, retro↔futuristic). That feeling lives in the *relationships* between tokens (whitespace, contrast character, saturation, shape language, imagery treatment, polish), not the tokens themselves — two brands can share the same hex + typeface and feel opposite. So a separate **vision pass reads the captured screenshots** and produces the *felt* layer:

- **Aesthetic descriptors** — a short controlled-ish vocabulary of adjectives ("clinical, high-contrast, minimalist, futuristic"), **each with an evidence phrase** tying it to what's on the page ("near-black canvas, single electric-violet accent, generous whitespace, hard corners"). This is the grounded version of Pomelli's "Clinical Midnight / Bio-Futuristic Sharpness" — read off the real render, not invented.
- **Mood axes** — the brand placed on a fixed set of 0–100 scales (minimal↔maximal, warm↔cool, playful↔serious, understated↔bold, budget↔premium, organic↔geometric, classic↔futuristic) so the vibe is comparable and repeatable, not just prose.
- **Character reads** — color mood (muted vs vibrant, mono vs multi), type personality (geometric vs humanist, technical vs editorial), shape language (sharp vs rounded), spatial density (airy vs packed), imagery style (photographic vs illustrated vs none; lighting; subjects).

Mechanics: **one bounded Claude vision call — Sonnet** (the read is interpretive and feeds the entire Aesthetic section + the coherence check, so it earns Sonnet over the QA visual-check's Haiku) **over the homepage viewport + full-page DataForSEO screenshot**, forced-tool output into a fixed schema, best-effort (a failed/degraded read omits the vibe layer and the guide still renders from the census). This is **not new infrastructure** — the QA agent already obtains a page screenshot (DataForSEO `page_screenshot`) and judges it with Claude vision (`qa_service`/`qa_visual` visual-render check); this reuses that exact pattern, one model tier up.

**Coherence check (the audit payoff).** Because §4.2 (measured tokens) and §4.3 (felt vibe) are produced independently, synthesis (§4.5) can *cross-check* them and flag **incoherence** — where the intended feel and the executed detail diverge. Example: the vibe read says "premium, minimalist" but the census shows 11 near-duplicate grays and cramped spacing → a flagged gap ("the aesthetic reads premium, but the execution is inconsistent — consolidate to 3 neutrals, open up spacing"). This is exactly the "here's where your brand is leaking" insight that makes the deliverable a sales asset, and it's only possible because vibe and tokens are read separately then compared.

Kept honest about its limits (surfaced in the guide's methodology note): a vibe read is an *interpretation*, motion/interaction feel isn't captured from static shots, and it's an LLM judgment that can be wrong — so it's presented as an observed reading the operator can edit, never as measurement.

### 4.4 Pull existing assets (no new calls)

Read the already-populated client-level canonical assets: `clients.brand_voice` (personality/tone/writing_style/vocabulary/messaging_themes/sample_phrases + the writer_execution_guide), `clients.detected_icp` (segments), `clients.differentiators`, the distilled **Voice & Audience Card** (tone_adjectives, person, must_use/never_use/discouraged terms, signature_phrases, cta_language, audience_pain_points/triggers/motivations/objections), `clients.logo_url` / `gbp.logo`, plus `clients.brand_guide_text` / `icp_text` (the human-authored seeds).

### 4.5 Synthesize (grounded LLM)

One or a few forced-tool calls produce the **Proposed** layer + naming: swatch names, palette roles + ratios + contrast pairings, named type scale, imagery/iconography direction, tagline, positioning statement, worked voice examples (headline/CTA/blurb/email), we-say/we-don't table, key messages, boilerplate, the **coherence check** (vibe vs tokens, §4.3), and the **gap analysis** per section. Grounded strictly on the extracted census (§4.2) + the aesthetic/vibe read (§4.3) + the pulled assets (§4.4) + the site copy captured in stage 1. **Guardrail (§5.3): a universal prompt exclusion for every client, plus — for `regulated` clients — a deterministic claim-shape input-filter on the synthesis corpus and an `awaiting_signoff` gate before render.**

### 4.6 Assemble + store

Write a **versioned `brand_guides` row** carrying the captured assets, the deterministic census, the aesthetic/vibe read, the synthesized layer, provenance, and the render storage paths (§9). Regenerating creates a new version; an operator-edited guide is never silently overwritten (mirrors the page-spec/voice-card "edited stays" pattern).

### 4.7 Render (PDF)

Build a self-contained `<!doctype html>` doc with an inline print `<style>` (new `_CSS`, A4/`@page`, cover, swatch grids, type specimens, do/don't blocks, SVG legends) → `client_report.render_pdf(html)` (WeasyPrint) → `_store_pdf` (private `reports` bucket) → `_signed_url`. Screenshots/logo inlined as base64 data URIs so the PDF is portable. Delivered to the client's Drive folder via the existing `client_report_schedule.deliver_report` path (email when SMTP lands).

**Render profiles.** One `profile: internal | client` flag renders the same stored record two ways — the only delta is the coherence/audit treatment. **internal** = the blunt audit in full ("11 near-dup grays, cramped spacing — leaking premium"). **client** = the identical findings **reframed as forward-looking "opportunities to sharpen"** (never diagnostic "your brand is broken"), feeding the Proposed layer's rationale, plus the existing white-label footer (`client_report_agency_name`). Both ship in v1; `storage_path`/`pdf_url` are per-profile.

### 4.8 Enforcement refresh loop (D1 — job #3, suggest-only in v1)

Ranked **last** of the three jobs and deliberately **suggest-only** in v1 — no new write path. The generated guide **surfaces** its refined voice/messaging as copyable suggestions with a link to the **existing** Brand Voice editor; the operator applies them knowingly through the existing `update()` path. Two facts force this shape:

- The **Voice & Audience Card cannot be written directly** — it is derived cache, rebuilt automatically when its fingerprint (rendered `brand_voice` + ICP text) changes. The only lever is the *source* `brand_voice`/`detected_icp`.
- Writing structured `brand_voice` via `update()` **flips `source→"user"`, which permanently blocks the client's automatic brand-voice scans** (`_scan_blocked`). An auto-apply would silently convert the client to manual-voice mode — a side effect the operator must choose, not inherit.

The guide's **messaging layer** (positioning statement, boilerplate, key messages, value proposition) has **no home in the current enforcement schema** (`brand_voice` / voice_card / `detected_icp` / `differentiators` — verified) and stays **deliverable-only**, stored in `brand_guides.synthesized`. Promote to a one-click apply loop in v1.1 only if operators ask; giving the messaging layer a schema home is a separate, explicit decision.

---

## 5. Design principles & guardrails

### 5.1 Reuse, don't reinvent
~70% of the module is assembly + render over data the suite already stores. The genuinely new capabilities are live-site visual extraction (§4.1–4.2) and the vision-based aesthetic/vibe read (§4.3) — and even the vibe read reuses the QA agent's existing screenshot+vision pattern. Do not build a second voice/ICP model; read the canonical ones.

### 5.2 Deterministic where it can be
All measurement (color census, clustering, type scale, contrast math, clear-space/min-size rules) is pure Python and unit-tested. The LLM only *names* and *proposes* — it never counts, measures, or reports a hex value it wasn't handed. (Mirrors the suite's "the LLM never counts words" page-spec discipline.)

### 5.3 Grounded synthesis — the guardrail (D3)

**Universal (every client, not flag-gated).** Synthesis may invent *brand* language (swatch names, taglines, aesthetic descriptors) but **never** a product claim, efficacy, dosage, safety/therapeutic claim, "FDA", or any fact not present in the pulled assets or captured copy — an explicit prompt exclusion list (reusing the spirit of the ecommerce `is_excluded_fact` hard-exclude rule). This prompt hygiene applies to a plumber's guide as much as a peptide's.

**Regulated clients — engaged by a manual per-client `regulated` flag.** Two additional deterministic protections fire only when the flag is set:

- **(a) Input-filter, not just output-scan.** Claim-*shape* patterns (an efficacy verb — treats/supports/boosts/reduces/clinically/proven — plus a health-outcome object) are matched against the **synthesis input corpus**, and any tripping sentence is **excluded before synthesis**. This closes the laundering hole: the client's *own site copy* is not a trusted claim source, so a gray-area claim already on their site can't be recombined into an agency-branded PDF.
- **(b) Pre-render sign-off gate.** The guide finalizes in an **`awaiting_signoff`** state before render/delivery, approvable only by an **admin or the client's owning staff member** (§6).

> **⚠️ Accepted residual risk (owner, 2026-09-15).** Protections (a)+(b) are **entirely** gated on the manual `regulated` flag — detection is not inferred, so a **forgotten flag on a regulated client means no input-filter and no sign-off gate.** Accepted deliberately to keep the flag as the single, explicit control (the always-on deterministic floor offered in review was declined). The universal prompt hygiene above still applies regardless.

### 5.4 Best-effort, degrade-never-fail
A dead page, an unreadable font, a missing logo, an LLM failure — each degrades that section (with an honest "not captured" note) and never aborts the guide. A client with no site still gets a guide from their existing voice/ICP assets (Documented-visual sections marked unavailable, Proposed-visual sections generated prescriptively from ICP + industry).

### 5.5 Freeze-aware
Guide *generation* is observation/deliverable, not client-site output, so it is **not** freeze-gated. The enforcement-refresh loop is **suggest-only in v1** (§4.8) — it writes no client assets itself (the operator applies suggestions through the existing editor), so there is nothing to freeze-gate. If a one-click auto-apply lands in v1.1 it inherits the scans' supersede guard; freeze-gating it is a v1.1 call.

---

## 6. Data model

New table `brand_guides` (RLS service-role only):

```
brand_guides
  id                uuid pk
  client_id         uuid fk clients on delete cascade
  version           int                  -- monotonic per client
  status            text                 -- queued|capturing|synthesizing|rendering|awaiting_signoff|done|error
  source_url        text                 -- the URL captured
  captured          jsonb                -- per-page: dom digest, screenshot paths, capture notes
  visual_census     jsonb                -- deterministic extract (colors/fonts/scale/logos/…)
  vibe_read         jsonb                -- aesthetic/vibe read (descriptors+evidence, mood axes, character reads)
  synthesized       jsonb                -- proposed layer (names/ratios/examples/gaps/coherence/tagline/…)
  edited            bool default false   -- operator edited → never auto-overwrite
  storage_path      text                 -- pdf in reports bucket
  pdf_url           text                 -- signed
  error             text
  generated_at      timestamptz
  created_at        timestamptz default now()
```

Async job type `brand_guide_generate` (add to the `async_jobs` job_type CHECK, rebuilt from the *live* constraint). One job runs capture → extract → synthesize → render. **Freeze-gated:** no (see §5.5). Registered in `SINGLE_JOB_REGISTRY` so it pings the initiator on completion.

Migration: `writer/supabase/migrations/<ts>_brand_guides.sql` (apply live). A new manual **`clients.regulated`** boolean (default false) is added by the same or a sibling migration — it gates the §5.3 deterministic guardrail and the `awaiting_signoff` status.

Notes:
- **`edited`** is set by the lightweight **structured-field editor** (§9) — drop/rename/flag-not-brand a swatch, replace a tagline/positioning line, edit a worked example (a structured-field edit, **not** a canvas — §13). The PDF renders from the (possibly edited) record; regenerate on an edited guide **warns and offers a new version** rather than overwriting. *(This is what makes `edited` reachable — without the edit surface the flag could never become true.)*
- **`awaiting_signoff`** holds a `clients.regulated` client's guide before render/delivery until an **admin or the client's owning staff member** approves (§5.3b).
- **Render profiles** (`internal`/`client`, §4.7) are a render-time parameter over the one record; `storage_path`/`pdf_url` are per-profile.

---

## 7. Verified reuse map (grounded in the live code, 2026-09-15)

| Need | Reuse | Location |
|------|-------|----------|
| Brand voice fields | `clients.brand_voice` jsonb (personality/tone/writing_style/vocabulary/messaging_themes/sample_phrases/writer_execution_guide) | `services/brand_voice_service.py`; nlp `/analyze-brand-voice` |
| ICP + differentiators | `clients.detected_icp` (segments: demographics/psychographics/messaging) + `clients.differentiators` (claim/mechanism/type) | `services/icp_service.py`; nlp `/analyze-business` |
| Distilled enforceable voice | Voice & Audience Card (must_use/never_use/discouraged, cta_language, audience_*) | `writer/nlp-api/voice_card.py` |
| Live-site HTML (rendered) | `scrapeowl_fetch(url, render_js=True)` — existing production scrape path | `services/website_scraper.py` |
| Screenshot capture + pixel palette | DataForSEO `page_screenshot` (no Chromium) → Pillow quantization for palette dominance | `services/qa_visual.py` (`capture_screenshot`); Pillow (existing dep) |
| Color/font census (**salvage, not drop-in**) | `census_styles`/`TokenCensus` are count-only + hard-wired to the Claude-Design *upload* format (regex over inline `style=`), no weight seam — **salvage the color/font normalization (~25 lines), write a new weight-aware census** over scraped CSS + screenshot-pixel dominance | `services/website_theme_precompile.py` |
| Vision-over-screenshot (aesthetic/vibe read) | Established pattern: DataForSEO `page_screenshot` + a Claude-vision judge (Sonnet here vs the QA check's Haiku) | QA agent (`services/qa_service.py` / `services/qa_visual.py` visual-render check) |
| Logo | `clients.logo_url` (manual, `client-logos` bucket) + `gbp.logo` fallback | `routers/files.py` `upload_logo`; `services/gbp_service.py` |
| PDF render + store + deliver | `render_pdf`, `_store_pdf`, `_signed_url`, `build_report_html`/`_CSS` pattern, `generate_client_report`/`enqueue_client_report`/`run_client_report_job` scaffold, `client_report_schedule.deliver_report` | `services/client_report.py`, `services/client_report_schedule.py` |
| Async job + completion ping | `async_jobs` + `job_worker` dispatch + `SINGLE_JOB_REGISTRY` | `services/job_worker.py`, `services/activity.py` |

**Real gaps this module fills:** (a) no live-URL visual extraction exists anywhere today (colors/fonts come from uploaded designs; logo is manual/GBP); (b) no aesthetic/"vibe" read of a brand's visuals exists — the QA vision check judges page *correctness*, not brand *feel*; (c) no imagery-direction concept beyond per-design image-slot labels.

---

## 8. Infrastructure (D4 — no headless browser)

- **No new browser, no new vendor, no new key.** Capture reuses the existing **ScrapeOwl** (rendered HTML) and **DataForSEO `page_screenshot`** (screenshot) production paths; palette pixel-dominance uses **Pillow** (already a platform-api dep). No Chromium in any Docker image; no Browserless; no `BRANDGUIDE_BROWSER_WS_URL`; no new Railway service; topology unchanged. This matches the suite's stated "no Chromium — heavy, memory-hungry, deploy-risky on Railway" posture (`qa_visual.py`).
- **No net-new Python dependency for capture** — httpx / Pillow / BeautifulSoup are already present. (A small clustering helper for the color census is stdlib/NumPy, both already deps.)
- **Sandbox caveat (unchanged in effect):** the `ar-tools` Claude Code environment egress policy blocks arbitrary external hosts (verified: `novalifepeptides.com` → proxy 403 on CONNECT), so live-site captures can't be exercised from a web session. But **production Railway egress is open and the suite already fetches arbitrary client sites in prod** (ScrapeOwl, QA's SSRF-guarded httpx, DataForSEO screenshots), so the worker path is a solved, exercised capability. Extraction *logic* is validated locally on fixtures; live *content* is verified on the deployed worker.

---

## 9. Frontend

- A **"Brand Guide"** card in the client workspace (Reporting/Setup section), route `clients/:id/brand-guide` (`pages/BrandGuide.tsx`), mirroring the Client Reports page: generate on-demand, history with live status polling (reuse `useResumableJob`), a **profile toggle** (internal / client, §4.7) for download/re-sign, and — post-generation — the Documented/Proposed section preview, the **structured-field editor** (§6: drop/rename/flag-not-brand a swatch, replace a tagline/positioning line, edit a worked example — sets `edited`), and the **suggest-only** "copy refined voice into Brand Voice" surface (§4.8, links to the existing editor).
- For a `regulated` client the card surfaces the **`awaiting_signoff`** state with an **admin / owning-staff** "approve & render" action (§5.3b).
- Inputs: source URL (defaults to `clients.website_url`), page-scope (§12 Q2), and a "regenerate" that versions (warns before overwriting an `edited` guide — §6).

---

## 10. Phasing

- **Phase 0 — extraction core (pure).** `services/brand_guide_extract.py`: the census/clustering/type-scale/logo-ranking helpers + fixtures + unit tests. No network. *(Prototype already proves the shape.)*
- **Phase 1 — capture (no browser).** ScrapeOwl (`render_js`) rendered-HTML + DataForSEO `page_screenshot` capture; `brand_guides` table (+ `clients.regulated`) + `brand_guide_generate` job (capture→extract→store census, no synth/render yet). Verified on the worker.
- **Phase 1.5 — aesthetic/vibe read.** The single Sonnet-vision pass over the homepage DataForSEO screenshot (§4.3) → `vibe_read`; reuses the QA screenshot+vision pattern. Best-effort; the guide still generates without it.
- **Phase 2 — synthesis (grounded).** The LLM Proposed-layer + the coherence check (vibe vs tokens) + the §5.3 guardrail (prompt + deterministic post-check) + unit tests on the pure post-check.
- **Phase 3 — render.** New PDF template/`_CSS` + WeasyPrint + store + Drive delivery.
- **Phase 4 — frontend + enforcement suggestions.** Workspace card/page, the two render profiles (§4.7), the structured-field editor (§9), the regulated sign-off gate, and the **suggest-only** voice/messaging surface (§4.8) — no auto-write.
- **Phase 5 (v1.1) — applications/mockups.** Reuse the Website-Builder theme render for in-context mockups.

Each phase is independently shippable and dark until the frontend lands. Gated on a `brand_guide_enabled` config flag (default False).

---

## 11. Acceptance criteria

1. Given a client with a live site, a generated guide's **Documented** color section lists the site's actually-dominant colors (**exact declared hex from scraped CSS, ranked by screenshot-pixel dominance, near-duplicates clustered**) with correct Hex/RGB/HSL — verified against a manual eyedropper on ≥3 real client sites. *(This is the acceptance test for the no-browser capture method — if the pixel-dominance palette proves unacceptably wrong here, revisit D4.)*
2. The **Typography** section reproduces the site's real typefaces + a plausible type scale (largest→smallest) with no invented font.
3. The **Audience** and **Voice** sections are populated from the client's stored ICP/voice with **≥1 worked example each** (headline, CTA, blurb) — never an empty adjective list.
4. The **Aesthetic & Art Direction** section names the brand's vibe with descriptors + mood-axis placements, each tied to a screenshot-evidence phrase, and surfaces ≥1 coherence gap where one exists (feel vs execution) — spot-checked against a human's read of the same site on ≥3 clients.
5. For a regulated client, **zero** invented product claims/efficacy/regulatory statements appear (deterministic post-check passes; spot-checked by a human on the peptide client). The vibe read describes *visual feel* only — it never asserts a product fact.
6. The guide renders to a portable PDF in the `reports` bucket + lands in the client's Drive folder.
7. A client with **no** site still produces a guide (visual sections marked unavailable/prescriptive; the vibe read is omitted, not faked) rather than erroring.
8. The enforcement refresh **never** overwrites user-authored `source:"user"` voice/ICP text.

---

## 12. Open questions — **Resolved (2026-09-15, design review)**

1. **Logo auto-extraction.** ✅ **Resolved:** suggest ranked candidates + **one-click adopt** (writes to `client-logos`, sets `logo_url`); **never silently overwrite** an existing uploaded logo — adoption requires an explicit "replace" when `logo_url` is already set.
2. **Capture scope.** ✅ **Resolved:** **homepage is the visual authority** (palette/fonts/type/vibe); **up to 2 auto-discovered pages** (a product/service + an about) captured for **logo candidates, imagery variety, and a consistency check only — not folded into the palette census**; operator-overridable.
3. **Proposed palette authority.** ✅ **Resolved:** **organize + recommend, never silently restate.** The Documented layer shows the *real* palette honestly (all 11 grays); the Proposed layer may *recommend* a consolidated system but flags every proposed swatch as a recommendation/substitution, and any color not on the site is marked "suggested," never "your brand color."
4. **Model selection.** ✅ **Resolved:** **Sonnet vision** for the aesthetic/vibe read (interpretive, feeds the whole Aesthetic section + coherence check — one tier above the QA visual-check's Haiku), **one call over the homepage viewport + full-page** DataForSEO screenshot (the +2 pages are not sent to the vibe call); Haiku for cheap naming, Sonnet for messaging/examples.
5. **Enforcement-refresh UX & freeze.** ✅ **Resolved:** **suggest-only in v1** (§4.8) — the guide surfaces copyable voice/messaging suggestions applied through the *existing* Brand Voice editor; no new write path, so **nothing to freeze-gate**. A one-click auto-apply loop is a v1.1 decision (and would inherit the supersede guard + the `source→"user"` lock-in warning).
6. **v1 depth of Applications/mockups.** ✅ **Resolved:** **defer to v1.1** (§10 Phase 5). The deliverable clears the Pomelli bar without them.

**Also settled in review:** how "regulated" is determined — a **manual per-client `regulated` flag** that *entirely* gates the §5.3 deterministic guardrail (with the accepted residual risk noted there); and the **sign-off approver** — admin or the client's owning staff member.

---

## 13. Explicitly out of scope for v1

- Generating an actual **logo** (image synthesis) — the guide documents/recommends, it does not draw a mark.
- Live editing of the brand guide in a visual **canvas**. *(Lightweight **structured-field** editing of the stored record IS in v1 — §9 / §6 — which is how `edited` becomes true; the visual canvas is what stays out.)*
- Multi-brand / sub-brand systems.
- Auto-applying the visual identity to the client's live site (that's the Website Builder's job).
- Print-production artifacts (bleed/crop marks, Pantone matching) beyond CMYK values.
