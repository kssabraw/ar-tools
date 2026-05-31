# Local SEO Port — C1 Backend Progress & Seam-Edit Checklist

**Branch:** `claude/youthful-clarke-Pzz3O` · **Phase:** C1 (backend core) · **Status:** ENGINE PORT DONE (unwired, awaiting runtime verification)

## Done

- Created `writer/pipeline-api/modules/local_seo/`.
- **Vendored + ported the NLP engine** (`_service.py`, from `local-seo-writer/services/nlp/main.py`):
  - Dropped `FastAPI` / CORS / `slowapi` imports; replaced the FastAPI `app` and the `Limiter` with inert `_RouteShim` / `_LimiterShim` so the original `@app.post(...)` / `@limiter.limit(...)` decorators stay in place (clean diff vs upstream) but become no-ops and leave the handler functions directly callable.
  - Repointed all credentials from `os.environ` to the shared `config.settings` (`google_nlp_api_key`, `dataforseo_login/password`, `scrapeowl_api_key`, `anthropic_api_key`) — **no new config keys needed**.
  - Neutralized auth/usage (`verify_api_key`, `_verify_jwt_get_user`, `_log_usage_direct`) to no-ops — pipeline-api is private-network; platform-api authenticates at the edge.
  - Made NLTK corpus download best-effort (non-fatal on import).
  - **C-poll conversion:** added `_drain_to_result(worker)` and switched both long-running handlers (`generate_page`, `reoptimize_page`) from `return await _sse_stream(_worker)` to `return await _drain_to_result(_worker)` — they now return plain dicts instead of SSE streams. (0 SSE returns remain; 2 drainer returns.)
  - Normalized line endings CRLF → LF.
- `url_filter.py` — vendored as-is.
- `router.py` — real `APIRouter(prefix="/local-seo", tags=["local_seo"])` exposing the **5 core endpoints** (`/analyze`, `/score-page`, `/generate-page`, `/reoptimize-page`, `/reoptimize-section`) with suite-style error handling; `SCHEMA_VERSION = "1.0"`. Deferred endpoints (business/brand-voice/find-page/augment/related-pages/social/rankability/press-release) are left inert in `_service.py`, **not** exposed.
- `__init__.py` — `from .router import router`.
- `requirements.txt` — added `scikit-learn==1.5.2` (numpy, beautifulsoup4, lxml, nltk, anthropic, httpx already present).

## Verification done (static only)

- `python -m py_compile` passes for `_service.py`, `url_filter.py`, `router.py`, `__init__.py`.
- AST check: all 10 request/response models and all 5 handler functions + `_drain_to_result` referenced by `router.py` exist in `_service.py`.

## NOT yet verified / deliberately deferred

- ⚠️ **No runtime/import test** — this container has no Python deps installed (`sklearn`, `nltk`, `anthropic`, …), so the module cannot be imported or exercised here. Must be smoke-tested in an env with deps (local `pip install -r requirements.txt`, or Railway).
- ⚠️ **Module is intentionally NOT wired into `main.py`** — pipeline-api does not import `modules.local_seo` yet, so it is inert and cannot break the running service. Wire it in (`app.include_router(local_seo_router)`) only after an import smoke-test passes.
- ⚠️ **NLTK corpora** must be pre-baked into the pipeline-api Docker image (add `python -m nltk.downloader stopwords punkt punkt_tab` to the Dockerfile) before deploy.
- **C1.1 follow-up:** route the engine's ~10 `anthropic.AsyncAnthropic(...)` call sites through the suite's shared `get_anthropic()` + `anthropic_max_concurrency` semaphore (pattern in `modules/brief/llm.py`) for shared 429 protection. Left as-is for C1 (behavior-identical to source).

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
