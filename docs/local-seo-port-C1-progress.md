# Local SEO Port — C1 Backend Progress & Seam-Edit Checklist

**Branch:** `claude/youthful-clarke-Pzz3O` · **Phase:** C1 (backend core) · **Status:** IN PROGRESS

## Done in this pass

- Created `writer/pipeline-api/modules/local_seo/`.
- **Vendored the engine verbatim** as the baseline to diff against (mirrors Appendix A.1's "raw import, then diff" approach):
  - `_service.py` ← `local-seo-writer/services/nlp/main.py` (6,378 lines, UNMODIFIED)
  - `url_filter.py` ← `local-seo-writer/services/nlp/url_filter.py` (249 lines, UNMODIFIED)
  - `__init__.py` (empty — module is NOT yet wired into `main.py`, so it is inert and cannot affect the running pipeline-api).

## Why the surgery wasn't completed in this pass

The faithful, low-risk port strategy is **shim the app-level seams, keep the engine code verbatim**. Executing that safely requires reading exact byte regions of `_service.py` and ideally running an import smoke-test. In the current web session: (a) large file-content reads are being suppressed to protect context, and (b) no Python deps are installed, so nothing can be import-checked. Rather than make ~30 unverifiable edits to a 6.4k-line file, the engine is vendored as-is and the exact edit list is recorded below for the next pass (ideally in an env with deps, or done in small verifiable chunks).

## C1 seam-edit checklist (line numbers are in `_service.py`)

### Header / app neutralization
- [ ] **L25-33 imports:** keep `from fastapi import HTTPException, Request, Depends`; keep `from fastapi.responses import StreamingResponse`; keep `pydantic`, `typing`, `collections`. **Drop** `FastAPI`, `Security`, `APIKeyHeader`, `CORSMiddleware`, and all three `slowapi` imports (L31-33).
- [ ] **L68 `app = FastAPI()`** → replace with identity shim so existing `@app.post(...)` decorators no-op but leave functions callable:
  ```python
  class _RouteShim:
      def post(self, *a, **k):
          def deco(fn): return fn
          return deco
      get = post
      def add_exception_handler(self, *a, **k): pass
      def add_middleware(self, *a, **k): pass
      class state: limiter = None
  app = _RouteShim()
  class _LimiterShim:
      def limit(self, *a, **k):
          def deco(fn): return fn
          return deco
  limiter = _LimiterShim()
  ```
- [ ] **L87-119** (real `Limiter(...)`, `add_exception_handler`, CORS `add_middleware`, `LimitRequestSizeMiddleware` block) → delete (shim above covers calls). Keep the `LimitRequestSizeMiddleware` class only if referenced elsewhere; it isn't — safe to drop.
- [ ] **L108-109** starlette middleware imports → drop.

### Config repoint
- [ ] **L81 / L124-134** env block: replace `os.environ.get(...)` reads with suite settings:
  ```python
  from config import settings
  GOOGLE_NLP_API_KEY = settings.google_nlp_api_key
  DATAFORSEO_LOGIN = settings.dataforseo_login
  DATAFORSEO_PASSWORD = settings.dataforseo_password
  SCRAPEOWL_API_KEY = settings.scrapeowl_api_key
  ANTHROPIC_API_KEY = settings.anthropic_api_key
  ```
  Drop `NLP_API_KEY`, `SUPABASE_*` (auth/usage are removed).

### Auth / usage removal (pipeline-api is private network)
- [ ] **L139 `verify_api_key`** → keep name, make body `return None` (it's referenced in `Depends(verify_api_key)` args which the shim ignores).
- [ ] **L148 `_verify_jwt_get_user`** → `return "internal"` (no network call).
- [ ] **L164 `_log_usage_direct`** → `return None` (no-op).

### Anthropic (C1: faithful; semaphore is a C1.1 follow-up)
- [ ] Leave the ~10 `anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)` call sites as-is for C1 (behavior-identical). **Follow-up C1.1:** route through the suite's shared `get_anthropic()` + `anthropic_max_concurrency` semaphore (pattern in `modules/brief/llm.py`) for shared 429 protection.

### Routes — core only (per locked decision)
Keep & expose: `/analyze` (L994), `/score-page` (L4188), `/generate-page` (L4780), `/reoptimize-page` (L5122), `/reoptimize-section` (L5361).
Deferred (leave as inert functions for now, do NOT expose in router): `/analyze-business`, `/analyze-brand-voice`, `/find-page-for-keyword`, `/augment-page`, `/related-pages`, `/generate-social-posts`, `/check-rankability`, `/generate-press-release`.

### New files to add (C1)
- [ ] `models.py` — re-export the core Pydantic request/response classes from `_service.py` (`AnalysisRequest/Response`, `ScorePageRequest/Response`, `GeneratePageRequest`, `ReoptimizePageRequest`, `ReoptimizeSectionRequest/Response`).
- [ ] `router.py` — suite-pattern `APIRouter(tags=["local_seo"])`; POST endpoints delegating to the engine handler functions; convert the two SSE handlers (`/generate-page`, `/reoptimize-page`) to **return the final result dict** (drop `StreamingResponse`) per the C-poll decision; add `schema_version: "1.0"` to responses.
- [ ] `__init__.py` → `from .router import router`.

### Wiring
- [ ] `main.py`: `from modules.local_seo import router as local_seo_router` + `app.include_router(local_seo_router)`.
- [ ] `requirements.txt`: add `scikit-learn==1.5.2` (nltk, numpy, beautifulsoup4, lxml already present). Remove the need for `slowapi` (not added).
- [ ] `Dockerfile`: ensure NLTK `stopwords`/`punkt` corpora are pre-downloaded at build (the source lazily downloads in `_get_stopwords()`; pre-bake to avoid runtime network).

## Then C2 (platform-api + data) and C3 (frontend) per the main plan.
