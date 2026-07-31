# Handoff — Ecommerce reoptimize latency & cost

**Created:** 2026-07-31
**Scope:** two agreed changes to the ecommerce reoptimize pipeline — (A) stop the auto-retry loop early when passes stop gaining, (B) stop paying serial wall-clock for public-spec fact research.
**Status:** nothing built yet. This doc is the investigation + the plan.

> This is a **separate file from the suite's living `HANDOFF.md`** (92 KB, root). Do not merge these two — that one is the suite-wide operational handoff; this one is scoped to a single piece of work and can be deleted once both changes ship.

---

## 1. What prompted this

An owner reoptimize of a Nova Life Peptides product page ("Buy L Carnitine",
`https://novalifepeptides.com/shop/l-carnitine-1200mg-10ml/`) appeared to be stuck.
It wasn't — but investigating it produced a full, timestamped profile of where a
reoptimize run spends its time, and surfaced two clear inefficiencies.

Incidental finding from the same investigation, **not in scope here but worth
knowing** (see §6): a job that had run a healthy 8 minutes was destroyed by an
nlp container restart and was **not retried**, despite `max_attempts: 2`.

---

## 2. The measured profile

Reference run: `async_jobs.id = 0ed8ca8e-0eeb-4149-82bc-1b3e5110631f`,
started `08:27:37Z`, completed `08:45:33Z` — **17m56s**, composite **49.7 → 73.3**
(voice 82.4). Reconstructed from nlp `[tokens]` log lines.

| # | Phase | Wall clock | Cost |
|---|---|---|---|
| 1 | DataForSEO SERP (15 URLs) | 16s | — |
| 2 | ScrapeOwl × 15 competitors (5 JS-retries, 3 hard fails) | 1m30s | — |
| 3 | TextRazor entities (25 from 9 pages) | 15s | — |
| 4 | `POST /score-ecommerce-page` — the "before" verdict | 2m30s | $0.123 |
| 5 | `distill-voice-card` | ~13s | — |
| 6 | `ecommerce-fact-research` — **in=110,066 tok**, 13 specs | 1m24s | **$0.372** |
| 7 | pass 1 rewrite → score | 4m12s | $0.243 |
| 8 | pass 2 rewrite → score | 3m39s | $0.223 |
| 9 | pass 3 rewrite → score | 3m44s | $0.228 |
| | **Total** | **17m56s** | **≈ $1.19** |

Two structural facts fall out of this:

- **~13 of the 18 minutes is Anthropic generation time across 8 serial calls.**
  Each call emits 6,000–7,300 output tokens, and output tokens set latency.
  Nothing is hung; this is arithmetic.
- **Fact research alone is 31% of the cost** ($0.372 of $1.19) for 13 specs that,
  by definition, never change (CAS number, PubChem CID, molecular formula/weight,
  IUPAC name, SMILES, solubility, melting point…).

---

## 3. Change A — early-stop when the loop plateaus

### The problem

`reoptimize_ecommerce_page` (`writer/nlp-api/main.py:8879`) runs a keep-best
rewrite→score loop up to `MAX_ECOMMERCE_AUTO_PASSES` (3). It breaks only when
`pass_score >= body.score_threshold` (75) or scoring returns `None`
(`main.py:8923`). **A run that is climbing slowly and a run that has flat-lined
are treated identically** — both burn all three passes.

Each extra pass costs **~3m40s and ~$0.22**.

### The evidence it matters

Last 13 completed reoptimizes for this client:

| Outcome | Count | Runtime |
|---|---|---|
| Cleared 75 (loop exits early) | 9 | 8.0–13.4 min |
| Plateaued below 75 (burned all 3 passes) | 4 | 13.7–20.8 min |

The four plateau cases: Tirzepatide 17.4→**68.8** (14.4 min), B12 37.4→**68.3**
(13.7 min), BPC-157 TB-500 55.1→**71.9** (14.0 min), L Carnitine 49.7→**73.3**
(17.9 min). Roughly **a third of runs** pay full price for a third pass and still
land short.

### ⚠️ Prerequisite — per-pass scores are currently unobservable

Before picking a threshold, this has to be measurable. Right now it is not:

- The loop's per-pass `pass_score` is **never logged** — the `[tokens]` lines
  record cost only (`main.py:8898`, `main.py:8913`).
- It **is** put on the SSE progress message (`main.py:8883`), but platform-api's
  `_stream_nlp` keeps only the terminal `done` event and **discards progress
  events** (`services/ecommerce_service.py:166-190`).
- Only the winning pass is persisted — `ecommerce_page_scores` for this run holds
  exactly two rows: `reoptimize_before` 49.7 and `reoptimize` 73.3.

**So: step 0 is a one-line `logger.info` of `pass_num` + `pass_score` in the loop.**
Ship that first, let it run over a batch, then calibrate the threshold against
real marginal-gain data rather than guessing.

### Proposed implementation

In the loop at `main.py:8879`, after `pass_score` is computed and keep-best has
been applied:

```python
# Plateau guard: a pass that gains almost nothing means the model has run out
# of headroom against this SERP — two more minutes will not find it. Only from
# pass 2 (pass 1 has no prior to compare against).
if (prev_best_score is not None and pass_score is not None
        and pass_score - prev_best_score < ECOMMERCE_MIN_PASS_GAIN):
    logger.info(f"reoptimize-ecommerce: plateau at pass {pass_num} "
                f"({prev_best_score} -> {pass_score}); stopping early")
    break
```

Notes for whoever builds it:

- Add `ECOMMERCE_MIN_PASS_GAIN = float(os.environ.get("ECOMMERCE_MIN_PASS_GAIN", "0"))`
  near `MAX_ECOMMERCE_AUTO_PASSES` (`main.py:238`). **Default 0 = disabled**, so
  merging is a no-op; enable on the `nlp` Railway service once calibrated.
  Starting guess once data exists: **3.0 points**.
- Capture `prev_best_score` *before* the keep-best update, or the comparison is
  against the value you just wrote.
- **Regression is a stronger stop signal than a small gain** — a negative delta
  satisfies the same condition, which is the behavior we want. Keep-best already
  protects the output.
- Do not change keep-best or the `>= score_threshold` break. This is purely an
  additional exit.
- The same loop shape exists for Local SEO; leave it alone for now — calibrate on
  ecommerce first.

### Tests

`writer/platform-api/tests/test_ecommerce.py` is the existing home for pure
ecommerce helpers, but this logic lives in nlp — use
`writer/nlp-api/tests/` (alongside `test_ecommerce_facts.py`). Extract the
stop decision into a pure helper (e.g. `should_stop_early(prev, cur, min_gain)`)
so it is unit-testable without the LLM: gain above threshold continues, gain
below stops, regression stops, `None` prior (pass 1) always continues,
`min_gain=0` never stops.

---

## 4. Change B — stop paying serial wall-clock for fact research

### The problem

`_research_public_facts` (`writer/nlp-api/main.py:328`) depends on **only**
`entity` (the keyword) and `page_type`. It is independent of the score, the SERP
analysis, the brand voice and the existing page. Yet it runs strictly between the
baseline score and the first rewrite, adding its full **1m24s** to the critical
path, and it re-runs **from scratch on every reoptimize of the same product**.

### ⚠️ Correction to the original framing

This was first described as "a clean ~1.5 min saving with no behavioral change /
one `asyncio.gather`". That understated it. The baseline score and the research
happen in **two different HTTP requests to nlp**, issued sequentially by
platform-api `reoptimize_url` (`services/ecommerce_service.py`): `score_page(...)`
→ `POST /score-ecommerce-page`, then `reoptimize_from(...)` →
`POST /reoptimize-ecommerce-page`, inside which the research runs. You cannot
overlap them from inside one function. Three real options:

**Option B1 — gather inside nlp (small win, trivial risk).**
In `_worker`, run `_ecommerce_mcs_block`, `_research_public_facts` and
`_resolve_voice_card` (`main.py:8815-8828`) concurrently via `asyncio.gather`.
All three are independent. Saves only the overlap — **~20–40s**. No API surface
change. Do this regardless; it is nearly free.

**Option B2 — cross-service parallel (full ~1m24s win).**
1. New nlp endpoint `POST /research-ecommerce-facts` wrapping `_research_public_facts`.
2. New optional `researched_facts` field on `ReoptimizeEcommerceRequest`
   (`main.py`, near `score_threshold`); when supplied, `_worker` skips its own
   research and renders the block from the supplied facts.
3. In platform-api `reoptimize_url`, `asyncio.gather` the score call and the
   research call, then thread the result into `reoptimize_from`.
4. `generate-ecommerce-page` runs the same research and can reuse the field.

**Option B3 — cache the facts (best long-run payoff).**
These specs are invariant. Cache by normalized compound name in an app-owned
table (mirroring `domain_site_size` / `brand_mentions`), long TTL. Every repeat
reoptimize of the same product then costs **$0 and 0s** instead of $0.37 and
1m24s. This client re-reoptimizes the same pages repeatedly with different
`notes` — L Carnitine alone was attempted three times today — so this is likely
the highest-value of the three.

**Recommendation:** ship **B1 + B3**. B1 is nearly free; B3 kills both the cost
and the latency permanently for the repeat case, which is the common case here.
B2 only helps the genuine first-ever run of a compound and carries the most API
surface change — defer it unless first-run latency is the specific complaint.

---

## 5. What NOT to change

- **Keep-best semantics** and the `>= score_threshold` break — correct as-is.
- **The score → rewrite ordering.** The rewrite genuinely consumes the score's
  `deficiencies` and `serp_analysis`; this serialization is real, not accidental.
- **`temperature=0`** on rewrite + score. Deliberate (2026-07-17) so a page
  reoptimizes identically run-to-run.
- **The `notes` threshold bypass** (`reoptimize_url` docstring). Supplying notes
  intentionally forces a rewrite even on a high-scoring page — that is the
  feature, not a bug, and it is why every page in these batches runs the full loop.

---

## 6. Out of scope but flagged — the retry bug

`run_reoptimize_url_job` (`writer/platform-api/services/ecommerce_service.py`,
`~line 840`) wraps the whole run in `try/except Exception` and writes
`status='failed'` directly. It **never routes through the retry path**, so
`max_attempts: 2` on the job row is decorative for this job type.

Observed cost of this on 2026-07-31: job `ff95ae5c` ran 8 minutes, the nlp
container restarted at `08:23:37Z` mid-stream, the SSE read died with
`ecommerce_provider_error`, and the entire run was discarded with `attempts: 1`.
The user had to notice and re-run by hand.

The classifier for this already exists — `_raise_if_transient_nlp` in the
`content_batch` path distinguishes 5xx/transport (retry) from 4xx (permanent),
and is already unit-tested in `tests/test_content_batch.py`. Wiring it in here is
small. **Not requested yet — raise it before building.**

Related environment notes:
- Every nlp log line carries `severity: error` because the service logs to
  stderr. Ignore the severity; read the message.
- Railway log retention only reaches back to the **current container**. After a
  restart the prior instance's logs are gone — capture anything you need
  immediately.

---

## 7. Quick reference

| Thing | Where |
|---|---|
| Retry loop | `writer/nlp-api/main.py:8879` |
| Threshold break | `writer/nlp-api/main.py:8923` |
| `MAX_ECOMMERCE_AUTO_PASSES` | `writer/nlp-api/main.py:238` |
| `_research_public_facts` | `writer/nlp-api/main.py:328` |
| Independent pre-rewrite calls (B1) | `writer/nlp-api/main.py:8815-8828` |
| `ReoptimizeEcommerceRequest` | `writer/nlp-api/main.py` (before `@app.post('/reoptimize-ecommerce-page')`) |
| `reoptimize_url` (platform) | `writer/platform-api/services/ecommerce_service.py` |
| SSE reader that drops progress events | `writer/platform-api/services/ecommerce_service.py:166-190` |
| Job runner that swallows retries | `writer/platform-api/services/ecommerce_service.py` (~840) |

Reference data — Supabase project `wvcthtmmcmhkybcesirb`, client
`be4044e0-e5cd-4d86-871a-b533301789e4` (Nova Life Peptides):

```sql
-- runtime + score movement per completed reoptimize
select payload->>'keyword' as keyword,
       result->>'prev_score' as prev_score,
       result->>'new_score'  as new_score,
       round(extract(epoch from (completed_at-started_at))/60.0, 1) as minutes
from async_jobs
where job_type='ecommerce_reoptimize_url' and status='complete'
  and payload->>'client_id'='be4044e0-e5cd-4d86-871a-b533301789e4'
order by created_at desc;
```

nlp service on Railway: project `2c718e53-73c8-4de8-bef8-7136f06b6ead`,
service `5477a749-39ef-43f0-99fc-bf245cd6d0d5`, env `7bd2e88e-8ead-4806-a0e0-673d34d66323`.
