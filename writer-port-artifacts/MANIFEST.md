# Writer Module Port — Source Artifacts Bundle

Gathered from the `kssabraw/ar-tools` repo + the `AR-Internal-Tools` Supabase
(`wvcthtmmcmhkybcesirb`) for porting the **Writer module** (degraded mode:
`schema_version_effective: "1.7-no-context"`, `no_citations: true`) into a
different project.

## ⚠️ Critical correction to the request's premise

- **There is no standalone "Writer PRD #1 v1.7" document.** The Writer PRD on
  disk is **v1.3** (`prd/content-writer-module-prd-v1.3.md`) plus a **v1.5
  change spec** (`prd/writer-module-v1_5-change-spec_2.md`). The PRD doc was
  *logically* bumped to v1.6 (Phase 3) and v1.7 (Phase 4) by the **Content
  Quality PRD** (`prd/content-quality-prd-v1_0.md`), but those bumps were
  implemented **directly in code, never written back into a v1.6/v1.7 PRD
  markdown file.** The header of `content-writer-module-prd-v1.3.md` still says
  1.3.
- **Therefore the authoritative "v1.7" spec is the source code**, not a
  document. The real Step list, prompts, schemas, and call inventory live in
  `src/writer_module/`. `src/writer_module/pipeline.py` is the orchestrator and
  the single best entry point. The PRDs explain *intent*; the code is *truth*.
- The 3 sample runs in `sample_outputs/` were generated in **FULL-CONTEXT**
  mode (`schema_version: "1.7"`, with brand guide + ICP + website analysis +
  citations) — **NOT** the degraded `1.7-no-context` path the port targets.
  No degraded-mode sample runs exist in the DB. Use `pipeline.py`'s degraded
  branches (documented below) to understand what changes.

## TIER → file map

| Request | Where it is |
|---|---|
| **1.1** Writer PRD v1.7 (steps, prompts, schemas, call inventory, degraded behavior) | `prd/content-writer-module-prd-v1.3.md` + `prd/writer-module-v1_5-change-spec_2.md` (intent) **and** `src/writer_module/*.py` (truth). Schemas: `src/models/writer.py`. |
| **1.2** Engineering Spec | `prd/engineering-implementation-spec-v1_1.md` (module contracts §6.5, §9.1–9.3; schema §3.1). |
| **2.3** intent_format_template table | `prd/content-brief-generator-prd-v2_0.md` §3.3 (table) + `src/framing.py` (per-rule regex impl) + `src/models/brief.py` (`IntentFormatTemplate`). |
| **2.4** Content Quality thresholds (R1–R7) | `prd/content-quality-prd-v1_0.md`. |
| **2.5** Sample Brief+SIE+Writer (+Research+Sources) JSON ×3 | `sample_outputs/run_*.json`. |
| **3.6** Writer source code | `src/writer_module/` (entry: `pipeline.py:run_writer`), call wrappers `src/llm.py`. |
| **3.7** Anthropic model IDs | `src/llm.py` (`CLAUDE_MODEL = "claude-sonnet-4-6"`); Haiku `claude-haiku-4-5-20251001` (nlp-api only, not Writer). Writer uses Sonnet for ALL calls. See report. |

## Sample run files
Each `sample_outputs/run_<slug>.json` = `{run_id, keyword, modules: [{module,
module_version, duration_ms, attempt_number, output_payload}]}` with all five
modules (brief 2.6, sie 1.4, research 1.1, writer 1.7, sources_cited 1.1) for
one run, status=complete. Runs: `restoration architect`, `sustainable design
firm`, `local law 97 consultant`.
