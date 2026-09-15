# Brand Guide Generator — Module PRD v1.0

**Status:** Proposed (not built). Draft for review + adversarial review.
**Owner decisions captured:** 2026-09-15 (see §2).
**Author context:** Seeded by a review of a Google Pomelli "Brand Book" export for Nova Life Peptides; the goal is a brand guide that is *more complete and in-depth* than that thin, visual-only deliverable, grounded in the suite's existing client assets.

> This document is the product/behaviour authority for the Brand Guide module. It reuses existing suite infrastructure wherever possible; §7 is the verified reuse map (grounded in a read-only inventory of the live code, 2026-09-15). Where this doc and a shared service disagree on *how* a thing works, the code wins and this doc is wrong — flag it.

---

## 1. What this is

A per-client tool that turns **a website URL + the client's existing ICP/differentiators/brand-voice assets** into a polished, in-depth **Brand Guide** — delivered as both:

1. a **client-facing PDF** (the deliverable; a soft sales asset — "here's your brand, here's where it's leaking, here's the system going forward"), and
2. a **structured, versioned record** that can *refresh* the suite's existing enforcement assets (`clients.brand_voice`, the Voice & Audience Card) so the guide isn't just a document — it tightens content generation.

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
| D1 | **Purpose** | **Both** — client-facing PDF *and* internal enforcement asset | Build the render pipeline AND the Voice-Card/brand_voice refresh loop (§6). |
| D2 | **Mode** | **Both** — "extensive documentation *and* in-depth professional proposals" | Every section is dual-layer (Documented + Proposed), with a gap analysis. This is an audit+guide, not a pure documentation tool. |
| D3 | **Creative license** | **Grounded synthesis** | The LLM may invent swatch names, taglines, aesthetic/imagery direction — but **NEVER** a product claim, efficacy statement, dosage, regulatory status, or any fact. Hard guardrail for regulated verticals (peptides, supplements, medical). See §5.3. |
| D4 | **Visual extraction** | **Headless render** (true computed styles), run via a **hosted headless API (Browserless), connected over CDP** | Chromium is NOT added to any suite service image; capture code is ordinary Playwright pointed at a remote endpoint by env var. See §4.1 + §8. Rationale: at ~1–3 guides/month a dedicated service or image bloat is wasteful; a pay-per-use render API is ~free at that volume, no topology change. |

**Not yet decided (open questions — §12):** logo auto-extraction vs manual-only; how many/which pages to capture; whether the Proposed-palette may *replace* extracted colors or only *organize* them; the exact enforcement-refresh UX (auto-suggest vs one-click apply); model selection per synthesis step.

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

### 4.1 Capture (headless render) 🆕

Render the homepage + a small set of key pages (see §12 Q2; v1 default: homepage + up to 2 linked pages — a product/service page and an about/contact page, discovered from nav). For each page collect: **computed styles across the DOM**, the **DOM** (for logo/nav discovery), and a **screenshot** (viewport + full-page).

- **Code is ordinary Playwright.** `sync_playwright()` → `chromium.connect_over_cdp(BRANDGUIDE_BROWSER_WS_URL)` when the env var is set (production → Browserless), else `chromium.launch()` with a local browser (dev/prototype). Same extraction either way.
- Computed styles are collected by walking every rendered element (`getBoundingClientRect` filters invisibles), weighting each value by **rendered area** so visually dominant colors/fonts rank first — not just most-frequent-in-source.
- Best-effort + bounded (per-page timeout, total page cap). A dead page adds a degraded note; the guide still generates from whatever rendered.

### 4.2 Extract (deterministic, no LLM) 🆕

Turn the raw computed-style dump into a **visual census** (pure Python, unit-testable):

- **Colors** — parse `color` (text, area-weighted) and `background-color` separately; **cluster near-duplicates** (Euclidean RGB distance ≤ tolerance) into representatives with a dominance `share`; emit Hex + RGB + HSL (CMYK computed for print). Drop transparent/near-transparent.
- **Fonts** — first family in each `font-family` stack, area-weighted → primary/secondary families; cross-reference `fonts.googleapis.com` hrefs for the canonical family names + weights.
- **Type scale** — distinct `font-size` px values, weighted, sorted → the real hierarchy.
- **Weights / radii / spacing** — frequency tables.
- **Logo candidates** — ranked: `og:image`, `<img>` with "logo" in src/alt/class, header/home-link image, favicon.

> **Prototype validation (2026-09-15):** this exact extractor, run against a representative fixture, recovered a full palette (including the four colors a human brand book named by hand), both fonts, a 7-step type scale, weights, radii, and 4 logo candidates. The census machinery is adapted from the Website Builder's `website_theme_precompile.py` color/font census (`census_styles`/`TokenCensus`), which today runs only on *uploaded* Claude Design files — this points the same idea at rendered live output. **Live-site runs are blocked in the Claude Code sandbox by egress policy** (same limitation as DataForSEO/nlp); they run on the deployed worker (Browserless) or in an allow-listed environment.

### 4.3 Aesthetic & Vibe read (vision over the screenshots) 🆕

The deterministic census (§4.2) captures the *ingredients* of the visual identity — exact colors, fonts, sizes, radii — but not the **aesthetic**: the gestalt a human feels in two seconds (minimal↔maximal, warm↔clinical, playful↔serious, budget↔premium, organic↔geometric, retro↔futuristic). That feeling lives in the *relationships* between tokens (whitespace, contrast character, saturation, shape language, imagery treatment, polish), not the tokens themselves — two brands can share the same hex + typeface and feel opposite. So a separate **vision pass reads the captured screenshots** and produces the *felt* layer:

- **Aesthetic descriptors** — a short controlled-ish vocabulary of adjectives ("clinical, high-contrast, minimalist, futuristic"), **each with an evidence phrase** tying it to what's on the page ("near-black canvas, single electric-violet accent, generous whitespace, hard corners"). This is the grounded version of Pomelli's "Clinical Midnight / Bio-Futuristic Sharpness" — read off the real render, not invented.
- **Mood axes** — the brand placed on a fixed set of 0–100 scales (minimal↔maximal, warm↔cool, playful↔serious, understated↔bold, budget↔premium, organic↔geometric, classic↔futuristic) so the vibe is comparable and repeatable, not just prose.
- **Character reads** — color mood (muted vs vibrant, mono vs multi), type personality (geometric vs humanist, technical vs editorial), shape language (sharp vs rounded), spatial density (airy vs packed), imagery style (photographic vs illustrated vs none; lighting; subjects).

Mechanics: one bounded Claude **vision** call over the viewport + full-page screenshots (`GENERATION` set aside — see model note §12 Q4), forced-tool output into a fixed schema, best-effort (a failed/degraded read omits the vibe layer and the guide still renders from the census). This is **not new infrastructure** — the QA agent already renders a page screenshot and judges it with Claude vision (`qa_service` visual-render check + the DataForSEO `page_screenshot` path); this reuses that established pattern.

**Coherence check (the audit payoff).** Because §4.2 (measured tokens) and §4.3 (felt vibe) are produced independently, synthesis (§4.5) can *cross-check* them and flag **incoherence** — where the intended feel and the executed detail diverge. Example: the vibe read says "premium, minimalist" but the census shows 11 near-duplicate grays and cramped spacing → a flagged gap ("the aesthetic reads premium, but the execution is inconsistent — consolidate to 3 neutrals, open up spacing"). This is exactly the "here's where your brand is leaking" insight that makes the deliverable a sales asset, and it's only possible because vibe and tokens are read separately then compared.

Kept honest about its limits (surfaced in the guide's methodology note): a vibe read is an *interpretation*, motion/interaction feel isn't captured from static shots, and it's an LLM judgment that can be wrong — so it's presented as an observed reading the operator can edit, never as measurement.

### 4.4 Pull existing assets (no new calls)

Read the already-populated client-level canonical assets: `clients.brand_voice` (personality/tone/writing_style/vocabulary/messaging_themes/sample_phrases + the writer_execution_guide), `clients.detected_icp` (segments), `clients.differentiators`, the distilled **Voice & Audience Card** (tone_adjectives, person, must_use/never_use/discouraged terms, signature_phrases, cta_language, audience_pain_points/triggers/motivations/objections), `clients.logo_url` / `gbp.logo`, plus `clients.brand_guide_text` / `icp_text` (the human-authored seeds).

### 4.5 Synthesize (grounded LLM)

One or a few forced-tool calls produce the **Proposed** layer + naming: swatch names, palette roles + ratios + contrast pairings, named type scale, imagery/iconography direction, tagline, positioning statement, worked voice examples (headline/CTA/blurb/email), we-say/we-don't table, key messages, boilerplate, the **coherence check** (vibe vs tokens, §4.3), and the **gap analysis** per section. Grounded strictly on the extracted census (§4.2) + the aesthetic/vibe read (§4.3) + the pulled assets (§4.4) + the site copy captured in stage 1. **Guardrail (§5.3) is enforced in the prompt AND with a deterministic post-check.**

### 4.6 Assemble + store

Write a **versioned `brand_guides` row** carrying the captured assets, the deterministic census, the aesthetic/vibe read, the synthesized layer, provenance, and the render storage paths (§9). Regenerating creates a new version; an operator-edited guide is never silently overwritten (mirrors the page-spec/voice-card "edited stays" pattern).

### 4.7 Render (PDF)

Build a self-contained `<!doctype html>` doc with an inline print `<style>` (new `_CSS`, A4/`@page`, cover, swatch grids, type specimens, do/don't blocks, SVG legends) → `client_report.render_pdf(html)` (WeasyPrint) → `_store_pdf` (private `reports` bucket) → `_signed_url`. Screenshots/logo inlined as base64 data URIs so the PDF is portable. Delivered to the client's Drive folder via the existing `client_report_schedule.deliver_report` path (email when SMTP lands).

### 4.8 Enforcement refresh loop (D1 — "Both")

After a guide is generated, **offer** to refresh the client's `brand_voice` + Voice Card from the guide's refined voice/messaging (opt-in; **never auto-overwrites** user-authored `source:"user"` text — same supersede-guard the scans already honour). This is how the guide feeds content generation without creating a **second, competing** voice system. The guide is a superset deliverable; the Voice Card stays the single enforcement authority.

---

## 5. Design principles & guardrails

### 5.1 Reuse, don't reinvent
~70% of the module is assembly + render over data the suite already stores. The genuinely new capabilities are live-site visual extraction (§4.1–4.2) and the vision-based aesthetic/vibe read (§4.3) — and even the vibe read reuses the QA agent's existing screenshot+vision pattern. Do not build a second voice/ICP model; read the canonical ones.

### 5.2 Deterministic where it can be
All measurement (color census, clustering, type scale, contrast math, clear-space/min-size rules) is pure Python and unit-tested. The LLM only *names* and *proposes* — it never counts, measures, or reports a hex value it wasn't handed. (Mirrors the suite's "the LLM never counts words" page-spec discipline.)

### 5.3 Grounded synthesis — the hard guardrail (D3)
For regulated clients the guide must **never** state or imply a product claim, efficacy, dosage, safety, "FDA", therapeutic indication, or any fact not present in the pulled assets or captured copy. Enforced two ways: (a) an explicit prompt exclusion list (reuse the spirit of the ecommerce `is_excluded_fact` / hard-exclude rule); (b) a deterministic post-generation scan of the synthesized copy for excluded-term patterns → flag/strip before render. Invented *brand* language (swatch names, taglines, aesthetic descriptors) is allowed; invented *claims* are not.

### 5.4 Best-effort, degrade-never-fail
A dead page, an unreadable font, a missing logo, an LLM failure — each degrades that section (with an honest "not captured" note) and never aborts the guide. A client with no site still gets a guide from their existing voice/ICP assets (Documented-visual sections marked unavailable, Proposed-visual sections generated prescriptively from ICP + industry).

### 5.5 Freeze-aware
Guide *generation* is observation/deliverable, not client-site output, so it is **not** freeze-gated. The enforcement-refresh loop (§4.7) writes client assets, so it should respect the same supersede guard the scans use; whether it's freeze-gated is an open call (§12 Q5).

---

## 6. Data model

New table `brand_guides` (RLS service-role only):

```
brand_guides
  id                uuid pk
  client_id         uuid fk clients on delete cascade
  version           int                  -- monotonic per client
  status            text                 -- queued|capturing|synthesizing|rendering|done|error
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

Migration: `writer/supabase/migrations/<ts>_brand_guides.sql` (apply live).

---

## 7. Verified reuse map (grounded in the live code, 2026-09-15)

| Need | Reuse | Location |
|------|-------|----------|
| Brand voice fields | `clients.brand_voice` jsonb (personality/tone/writing_style/vocabulary/messaging_themes/sample_phrases/writer_execution_guide) | `services/brand_voice_service.py`; nlp `/analyze-brand-voice` |
| ICP + differentiators | `clients.detected_icp` (segments: demographics/psychographics/messaging) + `clients.differentiators` (claim/mechanism/type) | `services/icp_service.py`; nlp `/analyze-business` |
| Distilled enforceable voice | Voice & Audience Card (must_use/never_use/discouraged, cta_language, audience_*) | `writer/nlp-api/voice_card.py` |
| Color/font census machinery | `census_styles` / `TokenCensus` (frequency tables over style values) — adapt for computed styles | `services/website_theme_precompile.py` |
| Vision-over-screenshot (aesthetic/vibe read) | Established pattern: render a page screenshot + judge with Claude vision (+ the DataForSEO `page_screenshot` path) | QA agent (`services/qa_service.py` visual-render check) |
| Logo | `clients.logo_url` (manual, `client-logos` bucket) + `gbp.logo` fallback | `routers/files.py` `upload_logo`; `services/gbp_service.py` |
| PDF render + store + deliver | `render_pdf`, `_store_pdf`, `_signed_url`, `build_report_html`/`_CSS` pattern, `generate_client_report`/`enqueue_client_report`/`run_client_report_job` scaffold, `client_report_schedule.deliver_report` | `services/client_report.py`, `services/client_report_schedule.py` |
| Async job + completion ping | `async_jobs` + `job_worker` dispatch + `SINGLE_JOB_REGISTRY` | `services/job_worker.py`, `services/activity.py` |

**Real gaps this module fills:** (a) no live-URL visual extraction exists anywhere today (colors/fonts come from uploaded designs; logo is manual/GBP); (b) no aesthetic/"vibe" read of a brand's visuals exists — the QA vision check judges page *correctness*, not brand *feel*; (c) no imagery-direction concept beyond per-design image-slot labels.

---

## 8. Infrastructure (D4)

- **Capture runs on a hosted headless API (Browserless) over CDP.** New env var `BRANDGUIDE_BROWSER_WS_URL` (+ token). Unset → local Chromium (dev/prototype). Set → remote (production). No Chromium in any suite Docker image; no new Railway service; topology unchanged.
- New Python dep: `playwright` on **platform-api only** (the worker runs the job). At ~1–3 guides/month the render cost is negligible and there is zero idle infra.
- Provisioning (deferred until build): a Browserless account + `BRANDGUIDE_BROWSER_WS_URL`/token on the `PLATFORM` Railway service. Until set, the module can still run in a dev/allow-listed env against a local browser.
- **Sandbox caveat:** the `ar-tools` Claude Code environment egress policy blocks arbitrary external hosts (verified: `novalifepeptides.com` → proxy 403 on CONNECT), so live-site captures cannot be exercised from a web session unless the host is allow-listed (the same Custom-policy switch used for Everhour). Extraction *logic* is validated locally on fixtures; live *content* is verified on the deployed worker.

---

## 9. Frontend

- A **"Brand Guide"** card in the client workspace (Reporting/Setup section), route `clients/:id/brand-guide` (`pages/BrandGuide.tsx`), mirroring the Client Reports page: generate on-demand, history with live status polling (reuse `useResumableJob`), download the PDF (re-signed URL), and — post-generation — the Documented/Proposed section preview + the "Refresh brand voice from this guide" opt-in (§4.7).
- Inputs: source URL (defaults to `clients.website_url`), page-scope (§12 Q2), and a "regenerate" that versions.

---

## 10. Phasing

- **Phase 0 — extraction core (pure).** `services/brand_guide_extract.py`: the census/clustering/type-scale/logo-ranking helpers + fixtures + unit tests. No network. *(Prototype already proves the shape.)*
- **Phase 1 — capture.** Playwright capture over CDP/local; `brand_guides` table + `brand_guide_generate` job (capture→extract→store census, no synth/render yet). Verified on the worker.
- **Phase 1.5 — aesthetic/vibe read.** The vision pass over the captured screenshots (§4.3) → `vibe_read`; reuses the QA screenshot+vision pattern. Best-effort; the guide still generates without it.
- **Phase 2 — synthesis (grounded).** The LLM Proposed-layer + the coherence check (vibe vs tokens) + the §5.3 guardrail (prompt + deterministic post-check) + unit tests on the pure post-check.
- **Phase 3 — render.** New PDF template/`_CSS` + WeasyPrint + store + Drive delivery.
- **Phase 4 — frontend + enforcement loop.** Workspace card/page + the opt-in Voice-Card/brand_voice refresh.
- **Phase 5 (v1.1) — applications/mockups.** Reuse the Website-Builder theme render for in-context mockups.

Each phase is independently shippable and dark until the frontend lands. Gated on a `brand_guide_enabled` config flag (default False).

---

## 11. Acceptance criteria

1. Given a client with a live site, a generated guide's **Documented** color section lists the site's actually-dominant colors (area-weighted, near-duplicates clustered) with correct Hex/RGB/HSL — verified against a manual eyedropper on ≥3 real client sites.
2. The **Typography** section reproduces the site's real typefaces + a plausible type scale (largest→smallest) with no invented font.
3. The **Audience** and **Voice** sections are populated from the client's stored ICP/voice with **≥1 worked example each** (headline, CTA, blurb) — never an empty adjective list.
4. The **Aesthetic & Art Direction** section names the brand's vibe with descriptors + mood-axis placements, each tied to a screenshot-evidence phrase, and surfaces ≥1 coherence gap where one exists (feel vs execution) — spot-checked against a human's read of the same site on ≥3 clients.
5. For a regulated client, **zero** invented product claims/efficacy/regulatory statements appear (deterministic post-check passes; spot-checked by a human on the peptide client). The vibe read describes *visual feel* only — it never asserts a product fact.
6. The guide renders to a portable PDF in the `reports` bucket + lands in the client's Drive folder.
7. A client with **no** site still produces a guide (visual sections marked unavailable/prescriptive; the vibe read is omitted, not faked) rather than erroring.
8. The enforcement refresh **never** overwrites user-authored `source:"user"` voice/ICP text.

---

## 12. Open questions (need owner input before/while building)

1. **Logo auto-extraction:** should the guide auto-adopt the best logo candidate off the site (and store it to `client-logos`), or only *suggest* candidates and keep `logo_url` manual? (Recommend: suggest + one-click adopt; never silently overwrite an uploaded logo.)
2. **Capture scope:** homepage only, or homepage + N key pages? Which pages (nav-discovered product/about, or operator-picked)? (Recommend: homepage + up to 2 auto-discovered, operator-overridable.)
3. **Proposed palette authority:** may the Proposed layer *replace/rationalize* extracted colors (e.g. collapse 11 grays → 3, nudge for contrast), or only *organize* the real ones? (Recommend: organize + recommend, never silently restate a color the site doesn't use — flag substitutions explicitly.)
4. **Model selection** per step — Haiku for naming, Sonnet for messaging/examples, and a **vision-capable Claude** for the aesthetic/vibe read (§4.3). Which model for the vibe read, and is one screenshot pass enough or should it see the full-page + a couple key pages? (Recommend: Sonnet vision, viewport + full-page homepage in one call; confirm.)
5. **Enforcement-refresh UX & freeze:** auto-suggest a diff vs one-click apply; and should the refresh respect client freeze? (Recommend: one-click apply of a shown diff; not freeze-gated since it edits internal assets, not site output.)
6. **v1 depth of Applications/mockups** — in v1 or deferred to v1.1? (Recommend defer.)

---

## 13. Explicitly out of scope for v1

- Generating an actual **logo** (image synthesis) — the guide documents/recommends, it does not draw a mark.
- Live editing of the brand guide in a canvas (it's a generated PDF + structured record; edits happen on the underlying assets or a regenerate).
- Multi-brand / sub-brand systems.
- Auto-applying the visual identity to the client's live site (that's the Website Builder's job).
- Print-production artifacts (bleed/crop marks, Pantone matching) beyond CMYK values.
