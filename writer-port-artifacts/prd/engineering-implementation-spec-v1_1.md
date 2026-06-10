# Engineering Implementation Spec
## [Product Name TBD] — Internal Content Generation Platform

**Version:** 1.1
**Date:** April 30, 2026
**Status:** Ready for Implementation
**Based on:** Platform PRD v1.3, Writer Module v1.5 Change Spec
**Repo:** net-new GitHub repository (separate from ShowUP Local)

---

## 1. Repository Structure

Single GitHub repository with two deployable services and one Lovable-managed frontend.

```
/
├── platform-api/               # FastAPI — orchestrator, client CRUD, auth, file parsing
│   ├── main.py
│   ├── routers/
│   │   ├── clients.py
│   │   ├── runs.py
│   │   ├── users.py
│   │   └── files.py
│   ├── services/
│   │   ├── orchestrator.py     # run dispatch and state machine
│   │   ├── file_parser.py      # PDF/DOCX/TXT/MD/JSON → text
│   │   ├── website_scraper.py  # ScrapeOwl + LLM extraction
│   │   └── job_worker.py       # async_jobs table polling loop
│   ├── middleware/
│   │   └── auth.py             # Supabase JWT verification
│   ├── models/                 # Pydantic schemas
│   ├── requirements.txt
│   ├── Dockerfile
│   └── railway.toml
│
├── pipeline-api/               # FastAPI — all 5 module endpoints
│   ├── main.py
│   ├── modules/
│   │   ├── brief/
│   │   ├── sie/
│   │   ├── research/
│   │   ├── writer/
│   │   └── sources_cited/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── railway.toml
│
├── supabase/
│   └── migrations/             # SQL migration files, applied in order
│       ├── 001_schema.sql
│       ├── 002_rls.sql
│       └── 003_indexes.sql
│
└── README.md
```

**Lovable frontend:** Managed as a separate Lovable project. Connects to the platform-api via environment variable (`VITE_PLATFORM_API_URL`). Not housed in this repo.

---

## 2. Service Topology

### 2.1 Railway Services

| Service | Name | Purpose | Exposes |
|---|---|---|---|
| Platform API | `platform-api` | Orchestration, client management, auth, file parsing, website scraping | Public HTTPS — called by Lovable frontend |
| Pipeline API | `pipeline-api` | All 5 content generation modules | Internal Railway private networking — called only by platform-api |

**Platform API** is the only service with a public URL. The frontend never talks to the pipeline API directly.

**Pipeline API** uses Railway's private networking (`pipeline-api.railway.internal`) — it is not publicly accessible. This means module endpoints are not exposed to the internet.

### 2.2 Inter-Service Communication

```
Lovable Frontend
      │ HTTPS
      ▼
platform-api (public)
      │ HTTP (Railway private network)
      ▼
pipeline-api (private)
      │
      ├── /brief
      ├── /sie
      ├── /research
      ├── /write
      └── /sources-cited
```

Platform API calls pipeline API synchronously with per-request timeouts:

| Module | Request Timeout |
|---|---|
| Brief | 130s |
| SIE | 130s |
| Research | 130s |
| Writer | 100s |
| Sources Cited | 20s |

### 2.3 Concurrency Model

Platform API uses FastAPI's async capabilities. The orchestrator runs each pipeline as an `asyncio` background task. Brief + SIE are dispatched with `asyncio.gather()` for true parallelism within each run. Up to 5 runs can be in-flight simultaneously (enforced by a concurrency check before dispatch).

---

## 3. Supabase Schema

### 3.1 Migration File: 001_schema.sql

#### `profiles` (extends Supabase Auth users)

```sql
create table profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  role         text not null default 'team_member'
                 check (role in ('admin', 'team_member')),
  full_name    text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Auto-create profile on new auth user
create or replace function handle_new_user()
returns trigger as $$
begin
  insert into profiles (id, full_name)
  values (new.id, new.raw_user_meta_data->>'full_name');
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();
```

#### `clients`

```sql
create table clients (
  id                              uuid primary key default gen_random_uuid(),
  name                            text not null,
  website_url                     text not null,
  website_analysis                jsonb,
  website_analysis_status         text not null default 'pending'
                                    check (website_analysis_status in ('pending', 'complete', 'failed')),
  website_analysis_error          text,
  brand_guide_source_type         text not null
                                    check (brand_guide_source_type in ('text', 'file')),
  brand_guide_text                text not null default '',
  brand_guide_file_path           text,
  brand_guide_original_filename   text,
  icp_source_type                 text not null
                                    check (icp_source_type in ('text', 'file')),
  icp_text                        text not null default '',
  icp_file_path                   text,
  icp_original_filename           text,
  archived                        boolean not null default false,
  created_by                      uuid references profiles(id),
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now()
);
```

#### `runs`

```sql
create table runs (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id),
  keyword           text not null,
  intent_override   text,
  sie_outlier_mode  text not null default 'safe'
                      check (sie_outlier_mode in ('safe', 'aggressive')),
  sie_force_refresh boolean not null default false,
  status            text not null default 'queued'
                      check (status in (
                        'queued', 'brief_running', 'sie_running',
                        'research_running', 'writer_running',
                        'sources_cited_running', 'complete', 'failed', 'cancelled'
                      )),
  error_stage       text,
  error_message     text,
  sie_cache_hit     boolean,
  total_cost_usd    numeric(10, 4),
  started_at        timestamptz,
  completed_at      timestamptz,
  created_by        uuid references profiles(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
```

#### `client_context_snapshots`

```sql
create table client_context_snapshots (
  id                            uuid primary key default gen_random_uuid(),
  run_id                        uuid not null unique references runs(id) on delete cascade,
  client_id                     uuid not null references clients(id),
  brand_guide_text              text,
  icp_text                      text,
  website_analysis              jsonb,
  website_analysis_unavailable  boolean not null default false,
  created_at                    timestamptz not null default now()
);
```

#### `module_outputs`

```sql
create table module_outputs (
  id              uuid primary key default gen_random_uuid(),
  run_id          uuid not null references runs(id) on delete cascade,
  module          text not null
                    check (module in ('brief', 'sie', 'research', 'writer', 'sources_cited')),
  status          text not null
                    check (status in ('running', 'complete', 'failed')),
  input_payload   jsonb,
  output_payload  jsonb,
  cost_usd        numeric(10, 4),
  duration_ms     integer,
  module_version  text,
  attempt_number  integer not null default 1,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz,
  unique (run_id, module, attempt_number)
);
```

#### `async_jobs`

```sql
create table async_jobs (
  id            uuid primary key default gen_random_uuid(),
  job_type      text not null check (job_type in ('website_scrape')),
  entity_id     uuid not null,               -- client_id for website_scrape
  status        text not null default 'pending'
                  check (status in ('pending', 'running', 'complete', 'failed')),
  attempts      integer not null default 0,
  max_attempts  integer not null default 2,
  payload       jsonb,
  result        jsonb,
  error         text,
  scheduled_at  timestamptz not null default now(),
  started_at    timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz not null default now()
);
```

### 3.2 Migration File: 002_rls.sql

```sql
-- Enable RLS on all tables
alter table profiles                  enable row level security;
alter table clients                   enable row level security;
alter table runs                      enable row level security;
alter table client_context_snapshots  enable row level security;
alter table module_outputs            enable row level security;
alter table async_jobs                enable row level security;

-- profiles: users read own; admins read all
create policy "users read own profile"
  on profiles for select
  using (auth.uid() = id);

create policy "admins read all profiles"
  on profiles for select
  using (exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));

create policy "admins update profiles"
  on profiles for update
  using (exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));

-- clients: all authenticated users read; only admins write
create policy "authenticated users read clients"
  on clients for select
  using (auth.role() = 'authenticated');

create policy "admins manage clients"
  on clients for all
  using (exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));

-- runs: all authenticated users read and insert
create policy "authenticated users read runs"
  on runs for select
  using (auth.role() = 'authenticated');

create policy "authenticated users create runs"
  on runs for insert
  with check (auth.role() = 'authenticated');

create policy "authenticated users update own runs"
  on runs for update
  using (created_by = auth.uid() or exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));

-- client_context_snapshots: all authenticated users read; service role writes
create policy "authenticated users read snapshots"
  on client_context_snapshots for select
  using (auth.role() = 'authenticated');

-- module_outputs: all authenticated users read; service role writes
create policy "authenticated users read module outputs"
  on module_outputs for select
  using (auth.role() = 'authenticated');

-- async_jobs: service role only (no direct client access)
-- No policies needed — service role bypasses RLS by default
```

### 3.3 Migration File: 003_indexes.sql

```sql
create index idx_clients_archived        on clients (archived);
create index idx_clients_name            on clients (name);
create index idx_runs_client_id          on runs (client_id);
create index idx_runs_status             on runs (status);
create index idx_runs_created_at         on runs (created_at desc);
create index idx_runs_created_by         on runs (created_by);
create index idx_module_outputs_run_id   on module_outputs (run_id);
create index idx_async_jobs_status       on async_jobs (status);
create index idx_async_jobs_scheduled_at on async_jobs (scheduled_at);
```

### 3.4 Storage Buckets

Two private Supabase Storage buckets:

| Bucket | Path Convention | Purpose | Status |
|---|---|---|---|
| `files` | `files/{user_id}/{file_id}/{original_filename}` | Brand guide and ICP file uploads (PDF/DOCX/TXT/MD/JSON) | Active in v1 |
| `article-assets` | `article-assets/{run_id}/{asset_id}.{ext}` | Reserved for generated article images and embedded media | **Placeholder only** — created in v1 but unused. The Writer Module v1.5 does not generate image references. Reserved here so v2 image-generation work doesn't require schema migration or Storage configuration. |

Both buckets are private. Access only via signed URLs minted by the platform-api after JWT verification.

---

## 4. Authentication Flow

### 4.1 Login (Lovable → Supabase Auth)

1. User submits email + password on `/login`
2. Lovable calls `supabase.auth.signInWithPassword()` directly (no platform-api involvement)
3. Supabase returns a session with a JWT access token
4. Lovable stores the session in memory / localStorage via the Supabase JS client
5. On subsequent API calls, Lovable includes the JWT in the `Authorization: Bearer <token>` header

### 4.2 JWT Verification (Platform API)

Every platform-api request (except health checks) passes through auth middleware:

```python
# middleware/auth.py (pseudocode)
async def verify_jwt(request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise HTTPException(401)
    
    # Verify with Supabase using the JWT secret
    user = supabase_admin.auth.get_user(token)
    if not user:
        raise HTTPException(401)
    
    # Fetch role from profiles table
    profile = supabase_admin.table("profiles").select("role").eq("id", user.id).single()
    request.state.user_id = user.id
    request.state.role = profile["role"]
```

### 4.3 Admin Route Guard

Any route requiring admin access checks `request.state.role == "admin"` and raises `403` if not met. This is a FastAPI dependency injected at the router level.

### 4.4 Session Refresh

The Supabase JS client on the frontend handles token refresh automatically. The platform-api does not manage sessions.

---

## 5. Platform API — Routes

Base URL: `https://platform-api-[hash].up.railway.app`

### 5.0 Standard Error Response Format

All non-2xx responses from the platform-api use a consistent shape:

```json
{
  "error": {
    "code": "string_identifier",
    "message": "Human-readable explanation",
    "details": { "...optional context..." },
    "request_id": "req_abc123"
  }
}
```

The `request_id` is the same correlation ID logged server-side (see Section 13), so support requests can be traced through Railway logs by pasting it into search.

#### Common Error Codes

| Code | HTTP | Meaning |
|---|---|---|
| `unauthenticated` | 401 | JWT missing or invalid |
| `forbidden` | 403 | User lacks required role (e.g. team_member attempting admin action) |
| `validation_error` | 422 | Request body fails Pydantic validation |
| `client_not_found` | 404 | Client ID does not exist |
| `run_not_found` | 404 | Run ID does not exist |
| `client_name_taken` | 409 | Duplicate client name on create |
| `last_admin_demotion` | 409 | Attempt to demote the only admin |
| `concurrency_limit` | 429 | 5 runs already in non-terminal states |
| `unsupported_file_type` | 422 | Uploaded MIME type not in allowlist |
| `file_too_large` | 413 | Upload exceeds 10 MB |
| `file_parse_error` | 422 | File could not be parsed (e.g. corrupt DOCX) |
| `scanned_pdf` | 422 | PDF has <50 chars after text extraction |
| `schema_version_mismatch` | 500 | Pipeline module returned unexpected `schema_version` (see Section 6.5) |
| `module_timeout` | 504 | Pipeline module exceeded its timeout |
| `internal_error` | 500 | Unhandled server exception |

The frontend uses `code` for programmatic handling (e.g., showing specific UI states) and `message` for display.

### 5.1 Health

```
GET /health
→ 200 { "status": "ok" }
No auth required.
```

### 5.2 Users (admin only)

```
GET /users
→ 200 [{ id, email, full_name, role, created_at }]

POST /users/invite
Body: { email: string, role: "admin" | "team_member" }
→ 201 { id, email, role }
(Sends Supabase magic link invitation)

PATCH /users/{user_id}/role
Body: { role: "admin" | "team_member" }
→ 200 { id, role }
Guard: cannot demote self if last admin

DELETE /users/{user_id}
→ 204
Guard: cannot delete self
```

### 5.3 Clients

```
GET /clients?archived=false
→ 200 [{ id, name, website_url, website_analysis_status, archived, created_at }]
Auth: all authenticated users

GET /clients/{client_id}
→ 200 {
    id, name, website_url,
    website_analysis, website_analysis_status, website_analysis_error,
    brand_guide_source_type, brand_guide_text, brand_guide_original_filename,
    icp_source_type, icp_text, icp_original_filename,
    archived, created_at, updated_at
  }
Auth: all authenticated users

POST /clients                         [admin only]
Body: {
  name: string,
  website_url: string,
  brand_guide_source_type: "text" | "file",
  brand_guide_text: string,           -- required if source_type=text
  brand_guide_file_id: uuid,          -- required if source_type=file (from /files upload)
  icp_source_type: "text" | "file",
  icp_text: string,
  icp_file_id: uuid
}
→ 201 { id, name, website_analysis_status: "pending", ... }
Side effect: enqueues website_scrape async_job

PATCH /clients/{client_id}            [admin only]
Body: same shape as POST (all fields optional)
→ 200 { updated client }
Side effect: if website_url changed, enqueues new website_scrape job

POST /clients/{client_id}/archive     [admin only]
→ 200 { id, archived: true }

POST /clients/{client_id}/reanalyze   [admin only]
→ 202 { job_id }
Side effect: enqueues website_scrape async_job immediately
```

### 5.4 File Uploads

Files are uploaded before client creation. The returned `file_id` is passed to `POST /clients`.

```
POST /files/upload
Content-Type: multipart/form-data
Body: { file: <binary>, field: "brand_guide" | "icp" }
→ 201 {
    file_id: uuid,
    original_filename: string,
    parsed_text: string,          -- extracted text, truncated to 150,000 chars if over
    truncated: boolean,
    format: "json" | "markdown" | "text"
  }
Guards:
  - Max file size: 10 MB (enforced before parsing)
  - Supported types: application/pdf, application/vnd.openxmlformats...(docx),
                     text/plain, text/markdown, application/json
  - PDF with <50 chars extracted → 422 "Scanned PDF detected"
  - File stored to Supabase Storage bucket: files/{user_id}/{file_id}/{filename}
```

### 5.5 Runs

```
GET /runs?client_id=&status=&search=&page=1&page_size=50
→ 200 {
    data: [{ id, keyword, client_id, client_name, status, sie_cache_hit,
             total_cost_usd, created_at, started_at, completed_at }],
    total: int,
    page: int
  }

GET /runs/{run_id}
→ 200 {
    id, keyword, client_id, status, sie_cache_hit,
    error_stage, error_message, total_cost_usd,
    created_at, started_at, completed_at,
    client_context_snapshot: { brand_guide_text, icp_text, website_analysis, website_analysis_unavailable },
    module_outputs: {
      brief:        { status, output_payload, cost_usd, duration_ms, module_version },
      sie:          { status, output_payload, cost_usd, duration_ms, module_version },
      research:     { status, output_payload, cost_usd, duration_ms, module_version },
      writer:       { status, output_payload, cost_usd, duration_ms, module_version },
      sources_cited:{ status, output_payload, cost_usd, duration_ms, module_version }
    }
  }

POST /runs
Body: {
  client_id: uuid,
  keyword: string,                   -- max 150 chars
  intent_override: string | null,
  sie_outlier_mode: "safe" | "aggressive",
  sie_force_refresh: boolean
}
→ 202 { run_id: uuid, status: "queued" }
Side effect: creates run + snapshot rows, dispatches orchestration background task
Guard: rejects if 5 or more runs currently in non-terminal states (returns 429 `concurrency_limit`)
Idempotency: v1 relies on frontend debounce only — the NewRunForm disables the submit
button on click and re-enables only after the response (or after 3s on network error).
No server-side `Idempotency-Key` in v1. If duplicate runs from misbehaving clients
become a real problem, server-side dedupe can be added in v1.x — see Section 14 Open Items.

POST /runs/{run_id}/cancel
→ 200 { id, status: "cancelled" }
Guard: only creator or admin
Side effect: sets cancellation flag; orchestrator checks flag between stages

POST /runs/{run_id}/rerun
→ 202 { run_id: uuid }            -- new run_id
Side effect: creates new run with same keyword/config, new snapshot from current client context

GET /runs/{run_id}/poll
→ 200 {
    run_id: uuid,
    status: string,
    completed_stages: ["brief", "sie", ...],
    error_stage: string | null,
    updated_at: timestamptz
  }
Lightweight endpoint. Frontend polls every 5 seconds while status is non-terminal.
```

### 5.6 Cost Dashboard (admin only)

```
GET /analytics/costs?group_by=day|client|module&from=&to=
→ 200 {
    rows: [{ dimension: string, cost_usd: number, run_count: int }],
    total_cost_usd: number
  }

GET /analytics/failures?from=&to=
→ 200 [{ run_id, keyword, client_name, error_stage, error_message, created_at }]
```

---

## 6. Pipeline Orchestration

### 6.1 Orchestration Flow (platform-api/services/orchestrator.py)

When `POST /runs` is called, after creating the DB rows, the platform-api fires a FastAPI `BackgroundTask`:

```python
# pseudocode — full implementation in orchestrator.py
async def orchestrate_run(run_id: uuid):
    try:
        # Check cancellation before each stage
        if await is_cancelled(run_id): return

        # Stage 1: Brief + SIE in parallel
        await set_status(run_id, "brief_running")  # also implies sie_running
        brief_result, sie_result = await asyncio.gather(
            call_module("brief",   run_id, build_brief_payload(run_id)),
            call_module("sie",     run_id, build_sie_payload(run_id)),
            return_exceptions=True
        )
        if isinstance(brief_result, Exception): raise StageError("brief", brief_result)
        if isinstance(sie_result, Exception):   raise StageError("sie",   sie_result)

        # Stage 2: Research (requires brief output)
        if await is_cancelled(run_id): return
        await set_status(run_id, "research_running")
        research_result = await call_module("research", run_id,
                                            build_research_payload(run_id, brief_result))
        if isinstance(research_result, Exception): raise StageError("research", research_result)

        # Cross-validate keywords match
        validate_keyword_consistency(brief_result, sie_result, research_result, run_id)

        # Stage 3: Writer (requires brief + sie + research + client_context)
        if await is_cancelled(run_id): return
        await set_status(run_id, "writer_running")
        writer_result = await call_module("writer", run_id,
                                          build_writer_payload(run_id, brief_result,
                                                               sie_result, research_result))
        if isinstance(writer_result, Exception): raise StageError("writer", writer_result)

        # Stage 4: Sources Cited
        if await is_cancelled(run_id): return
        await set_status(run_id, "sources_cited_running")
        sources_result = await call_module("sources_cited", run_id,
                                           build_sources_payload(run_id, writer_result,
                                                                  research_result))
        if isinstance(sources_result, Exception): raise StageError("sources_cited", sources_result)

        # Complete
        await set_status(run_id, "complete")
        await update_total_cost(run_id)

    except StageError as e:
        await set_status(run_id, "failed", error_stage=e.stage, error_message=str(e))
    except Exception as e:
        await set_status(run_id, "failed", error_stage="unknown", error_message=str(e))
```

### 6.2 `call_module` Pattern

```python
async def call_module(module: str, run_id: uuid, payload: dict) -> dict:
    # Save input payload to module_outputs
    output_id = await create_module_output(run_id, module, payload)

    # Call pipeline API with timeout
    timeout = MODULE_TIMEOUTS[module]
    try:
        start = time.time()
        response = await http_client.post(
            f"{PIPELINE_API_URL}/{module}",
            json=payload,
            timeout=timeout
        )
        duration_ms = int((time.time() - start) * 1000)

        if response.status_code != 200:
            raise ModuleHTTPError(response.status_code, response.text)

        result = response.json()
        await save_module_output(output_id, result, duration_ms, cost=result.get("cost_usd"))
        return result

    except (httpx.TimeoutException, ModuleHTTPError) as e:
        # One automatic retry on timeout or 5xx
        if is_retriable(e) and attempt == 1:
            return await call_module(module, run_id, payload, attempt=2)
        await fail_module_output(output_id, str(e))
        raise StageError(module, e)
```

### 6.3 Cancellation

The orchestrator checks `is_cancelled(run_id)` before each stage by reading the `status` column from Supabase. If `cancelled`, the orchestrator exits immediately without dispatching further modules.

The `POST /runs/{run_id}/cancel` endpoint simply sets `status = 'cancelled'` in Supabase. The next cancellation check in the orchestrator loop picks it up.

### 6.4 Startup Recovery

On `platform-api` startup:

```python
# Find runs stuck in non-terminal states (platform crashed mid-run)
stuck_runs = supabase.table("runs").select("id").in_("status", [
    "queued", "brief_running", "sie_running",
    "research_running", "writer_running", "sources_cited_running"
]).execute()

# Mark them failed with recovery message
for run in stuck_runs:
    await set_status(run.id, "failed",
                     error_stage="recovery",
                     error_message="Service restarted mid-run. Please re-run.")
```

### 6.5 Module Schema Version Validation

Every pipeline module returns a `schema_version` field in its output. The orchestrator validates this against an expected-version registry **strictly** — any mismatch (major or minor) fails the run immediately.

#### Version Registry

```python
# platform-api/services/orchestrator.py
EXPECTED_MODULE_VERSIONS = {
    "brief":         "1.7",
    "sie":           "1.0",
    "research":      "1.1",
    "writer":        "1.5",
    "sources_cited": "1.1",
}
```

This registry is the single source of truth. When a module is upgraded, the registry must be updated in the same commit that updates the orchestrator's payload-building or output-consuming logic.

#### Validation Rule

After every successful `call_module` invocation:

```python
expected = EXPECTED_MODULE_VERSIONS[module]
actual   = result.get("schema_version")

if actual != expected:
    raise SchemaVersionMismatch(
        module=module,
        expected=expected,
        actual=actual,
        run_id=run_id
    )
```

#### Failure Behavior

A schema version mismatch:

- Aborts the current run immediately (no retry — this is a deployment bug, not a transient error)
- Marks the run as `failed` with `error_stage = <module>` and `error_message = "schema version mismatch: expected 1.7, got 1.8"`
- Returns `500 schema_version_mismatch` to the calling client (frontend)
- Logs the mismatch at `ERROR` level with both versions and the offending module name (see Section 13)

#### Writer Module Special Cases

The Writer Module emits three distinct version strings depending on input completeness (per Writer v1.5 spec):

- `"1.5"` — full v1.5 behavior with client_context
- `"1.5-no-context"` — v1.4 fallback (client_context omitted)
- `"1.5-degraded"` — v1.4 fallback (all client context fields empty)

The orchestrator's validation accepts all three for the Writer module:

```python
WRITER_ACCEPTED_VERSIONS = {"1.5", "1.5-no-context", "1.5-degraded"}
```

In v1, the platform always sends `client_context`, so `"1.5"` is the expected case. The other two would indicate a bug in the platform (client context not being attached) or a deliberate test scenario. Either way, the run completes successfully — but the version is logged so anomalies are visible in dashboards.

---

## 7. Async Jobs (Website Scraping)

### 7.1 Enqueue

When a client is created or website_url is edited:

```python
await supabase.table("async_jobs").insert({
    "job_type": "website_scrape",
    "entity_id": client_id,
    "payload": { "website_url": client.website_url, "client_id": str(client_id) }
})
```

### 7.2 Worker Loop

`platform-api` runs a background asyncio loop that polls `async_jobs` every 10 seconds:

```python
async def job_worker():
    while True:
        await asyncio.sleep(10)
        job = await claim_next_job()   # SELECT ... FOR UPDATE SKIP LOCKED
        if job:
            await process_job(job)

async def process_job(job):
    if job.job_type == "website_scrape":
        await run_website_scrape(job)
```

`SELECT ... FOR UPDATE SKIP LOCKED` ensures two platform-api instances (if Railway ever scales to 2) don't double-process the same job.

### 7.3 Website Scrape Logic

```python
async def run_website_scrape(job):
    client_id = job.payload["client_id"]
    website_url = job.payload["website_url"]

    try:
        # 1. Scrape homepage via ScrapeOwl
        html = await scrapeowl_fetch(website_url, timeout=45)

        # 2. LLM extraction — single call
        result = await llm_extract_website_data(html)
        # LLM prompt targets: services[], locations[], contact_info{phone,email,address,hours}
        # Returns structured JSON matching website_analysis schema

        # 3. Persist to client record
        await supabase.table("clients").update({
            "website_analysis": result,
            "website_analysis_status": "complete"
        }).eq("id", client_id)

    except Exception as e:
        await supabase.table("clients").update({
            "website_analysis_status": "failed",
            "website_analysis_error": str(e)
        }).eq("id", client_id)
```

**Website analysis output schema (stored in `website_analysis` jsonb column):**

```json
{
  "services": ["Furnace Installation", "AC Repair", "..."],
  "locations": ["Orange County", "Anaheim", "..."],
  "contact_info": {
    "phone": "(714) 555-0100",
    "email": "info@example.com",
    "address": "123 Main St, Anaheim CA 92801",
    "hours": "Mon-Fri 8am-6pm"
  }
}
```

---

## 8. File Parsing

All file parsing happens in the platform-api at upload time (`POST /files/upload`). Parsed text is returned in the response and stored in the client's `brand_guide_text` / `icp_text` field.

### 8.1 Parser Selection

```python
PARSERS = {
    "application/pdf":        parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
    "text/plain":             parse_text,
    "text/markdown":          parse_markdown,
    "application/json":       parse_json,
}
```

### 8.2 Per-Format Rules

| Format | Library | Output | Rejection Condition |
|---|---|---|---|
| PDF | `pypdf` | Extracted plain text | <50 chars after extraction (scanned image) |
| DOCX | `python-docx` | Extracted text from paragraphs + table cells | Unreadable/corrupt file |
| TXT | `open()` + `read()` | Raw text | Not UTF-8 decodable |
| MD | `open()` + `read()` | Raw text with Markdown preserved | Not UTF-8 decodable |
| JSON | `json.loads()` + `json.dumps(indent=2)` | Pretty-printed JSON string | Invalid JSON |

### 8.3 Format Detection

```python
# Detect format for downstream (writer distillation step needs to know)
def detect_format(content: str, mime_type: str) -> str:
    if mime_type == "application/json":
        return "json"
    if mime_type == "text/markdown" or content.strip().startswith("#"):
        return "markdown"
    return "text"
```

Format is stored in the snapshot as `brand_guide_format` so the writer's distillation LLM knows how to parse it.

### 8.4 Truncation

If parsed text exceeds 150,000 characters, truncate at the nearest sentence boundary below the limit and return `truncated: true` in the response. Do not truncate mid-word.

---

## 9. Pipeline API — Module Endpoints

Base URL: `http://pipeline-api.railway.internal` (private network only)

All endpoints: `POST /{module}` → `200 { output_payload... , cost_usd, schema_version }`

Errors: `422` for schema validation failures (no retry), `500` for transient errors (one retry from orchestrator).

### 9.1 Standard Input Envelope

Every pipeline API endpoint receives a `run_id` for idempotency:

```json
{
  "run_id": "uuid",
  "attempt": 1,
  ...module-specific fields...
}
```

Modules that receive a duplicate `run_id` + `attempt` combination return the cached result without re-running.

### 9.2 Module Endpoints Summary

| Path | Key Inputs | Key Outputs |
|---|---|---|
| `POST /brief` | `keyword`, `location_code`, `intent_override` | Brief JSON (headings, intent, word targets, FAQ targets) |
| `POST /sie` | `keyword`, `location_code`, `outlier_mode`, `force_refresh` | `terms.required[]`, `terms.avoid[]`, `word_count_target`, `sie_cache_hit` |
| `POST /research` | `keyword`, `brief_output` | `citations[]` with excerpts and relevance scores |
| `POST /write` | `brief_output`, `sie_output`, `research_output`, `client_context` | `article[]`, `citation_usage`, `brand_voice_card_used`, `brand_conflict_log[]` |
| `POST /sources-cited` | `writer_output`, `research_output` | Final article Markdown with formatted Sources Cited section |

### 9.3 Client Context in Writer Payload

```json
{
  "run_id": "uuid",
  "attempt": 1,
  "brief_output": { ...from brief module... },
  "sie_output": { ...from sie module... },
  "research_output": { ...from research module... },
  "client_context": {
    "brand_guide_text": "...",
    "brand_guide_format": "json" | "markdown" | "text",
    "icp_text": "...",
    "icp_format": "json" | "markdown" | "text",
    "website_analysis": { ...or null... },
    "website_analysis_unavailable": false
  }
}
```

### 9.4 Image References — Out of Scope for v1

The Writer Module v1.5 does not generate, reference, or embed images in article output. Final articles are pure Markdown text with citation markers — no `![alt](src)` image tags.

The `article-assets` Supabase Storage bucket (Section 3.4) is reserved for v2 work. When image generation is added later:
- Writer output schema will gain `images[]` and inline image markers (e.g., `{{img_1}}`)
- A new pipeline stage between Writer and Sources Cited will materialize image markers into Markdown image tags pointing to signed URLs from the bucket
- No platform schema changes will be required

---

## 10. Frontend Architecture (Lovable)

### 10.1 Environment Variables

```
VITE_PLATFORM_API_URL=https://platform-api-[hash].up.railway.app
VITE_SUPABASE_URL=https://[project].supabase.co
VITE_SUPABASE_ANON_KEY=[anon key]
```

### 10.2 Routes

| Path | Component | Auth | Admin Only |
|---|---|---|---|
| `/login` | `LoginScreen` | None | No |
| `/` | Redirect to `/runs` | Required | No |
| `/runs` | `RunDashboard` | Required | No |
| `/runs/new` | `NewRunForm` | Required | No |
| `/runs/:runId` | `RunDetail` | Required | No |
| `/clients` | `ClientList` | Required | No |
| `/clients/new` | `ClientForm` | Required | Admin |
| `/clients/:clientId` | `ClientDetail` | Required | Admin (edit); all (view) |
| `/admin/users` | `UserManagement` | Required | Admin |

### 10.3 Key Components

**`AuthProvider`**
Wraps the entire app. Initializes Supabase client, subscribes to `onAuthStateChange`, exposes `session`, `user`, `profile` (including `role`) via context. All routes consume this context.

**`RequireAuth` / `RequireAdmin`**
Route guards. `RequireAuth` redirects to `/login` if no session. `RequireAdmin` renders a 403 screen if `profile.role !== 'admin'`.

**`useRunPoller(runId)`**
Custom hook. Polls `GET /runs/:runId/poll` every 5 seconds while the run is in a non-terminal state. Stops automatically when status becomes `complete`, `failed`, or `cancelled`. Invalidates the full run query on completion so the detail view refreshes.

```typescript
// Usage
const { status, completedStages } = useRunPoller(runId);
```

**`ClientForm`**
Handles both "Paste Text" and "Upload File" tabs for brand guide and ICP. On file select, immediately calls `POST /files/upload` and shows a parsing status indicator. Stores the returned `file_id` and `parsed_text` in form state. On submit, sends `file_id` to `POST /clients` if file path was used.

**`NewRunForm`**
Basic fields: client dropdown, keyword input. Advanced options (collapsed by default): intent override select, SIE outlier mode toggle (safe/aggressive), force refresh checkbox. On submit, calls `POST /runs` and redirects to `/runs/:runId` to begin polling.

**Submit-button debounce (idempotency control):** the submit button is disabled the moment it is clicked, remains disabled while the `POST /runs` request is in flight, and stays disabled for an additional 2 seconds after a successful response. This is the v1 mechanism for preventing duplicate runs from rapid double-clicks. Server-side `Idempotency-Key` handling is deferred to v2 if duplicate runs become a problem in practice.

**`RunDetail`**
Shows run status at the top (live via `useRunPoller`). Below status, renders module output tabs: Brief, SIE, Research, Writer, Sources Cited — each tab shows the JSON output when the stage is complete, or a spinner when running. Article Review tab (active only when status = `complete`) shows the rendered Markdown and export controls.

**`ArticlePreview`**
Renders final Markdown from `sources_cited` module output. Two views: "Preview" (rendered HTML) and "Markdown" (raw source). Export buttons: Copy Markdown, Copy HTML, Download `.md`.

**`CostDashboard`** (admin only)
Displays aggregate cost tables grouped by day/client/module. Fetches `GET /analytics/costs`.

### 10.4 API Client Pattern

Use a thin wrapper around `fetch` that injects the Supabase JWT automatically:

```typescript
// lib/api.ts
async function apiRequest(path: string, options?: RequestInit) {
  const session = await supabase.auth.getSession();
  return fetch(`${PLATFORM_API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${session.data.session?.access_token}`,
      ...options?.headers,
    },
  });
}
```

### 10.5 State Management

No global state manager (Redux, Zustand) needed in v1. Use:
- **Supabase JS client** for auth state
- **TanStack Query (React Query)** for server state (runs list, run detail, clients list)
- **React local state** for form state

Lovable supports TanStack Query natively.

---

## 11. Environment Variables

### 11.1 `platform-api` Railway Service

```
# Supabase
SUPABASE_URL=https://[project].supabase.co
SUPABASE_ANON_KEY=[anon key]
SUPABASE_SERVICE_ROLE_KEY=[service role key]   # used for admin operations + RLS bypass

# Pipeline API
PIPELINE_API_URL=http://pipeline-api.railway.internal

# External APIs (used by platform-api for website scraping)
SCRAPEOWL_API_KEY=[key]
OPENAI_API_KEY=[key]                           # or ANTHROPIC_API_KEY for website extraction LLM

# App config
MAX_CONCURRENT_RUNS=5
JOB_WORKER_POLL_INTERVAL_SECONDS=10
```

### 11.2 `pipeline-api` Railway Service

```
# Supabase (for SIE caching)
SUPABASE_URL=https://[project].supabase.co
SUPABASE_SERVICE_ROLE_KEY=[service role key]

# External APIs
DATAFORSEO_LOGIN=[login]
DATAFORSEO_PASSWORD=[password]
SCRAPEOWL_API_KEY=[key]
OPENAI_API_KEY=[key]
ANTHROPIC_API_KEY=[key]
GOOGLE_APPLICATION_CREDENTIALS=[path or JSON string for NLP API]

# Module config
SIE_CACHE_TTL_DAYS=7
```

---

## 12. Deployment Sequence

Build and deploy in this order to avoid dependency issues.

### Phase 1 — Supabase

1. **Install Supabase CLI** locally on the engineer's machine: `brew install supabase/tap/supabase` (macOS) or follow [docs](https://supabase.com/docs/guides/cli/getting-started) for other platforms
2. **Initialize the project** in the repo root: `supabase init` — creates the `/supabase` directory with config and migrations folder
3. **Create the new Supabase project** via the Supabase dashboard (separate from ShowUP Local). Note the project ref (e.g. `abcdefghijkl`).
4. **Link the local repo** to the project: `supabase link --project-ref [ref]` — prompts for the database password
5. **Add migration files** to `/supabase/migrations/` with timestamp-prefixed naming convention: `[YYYYMMDDhhmmss]_[description].sql`. Place the three migration files from Section 3 in order:
   - `20260430120000_schema.sql` (Section 3.1)
   - `20260430120100_rls.sql` (Section 3.2)
   - `20260430120200_indexes.sql` (Section 3.3)
6. **Apply migrations** to the linked project: `supabase db push`
7. **Create Storage buckets** (Section 3.4) via Supabase dashboard → Storage:
   - `files` (private)
   - `article-assets` (private; placeholder for v2)
8. **Create the first admin user** via Supabase dashboard → Auth → Users → "Add user" → enter email and temporary password
9. **Promote that user to admin** by running in the SQL editor:
   ```sql
   update profiles set role = 'admin' where id = (
     select id from auth.users where email = 'your-email@example.com'
   );
   ```

**Local development tip:** run `supabase start` to spin up a local Postgres + Auth stack for testing migrations before pushing them to the linked project. Run `supabase db reset` to wipe and reapply all migrations locally.

**Production migration workflow going forward:** create a new migration file with `supabase migration new [description]`, edit the generated SQL, test locally with `supabase db reset`, then push with `supabase db push`.

### Phase 2 — Pipeline API

1. Create `pipeline-api` Railway service from GitHub repo (`/pipeline-api` root)
2. Set all pipeline-api environment variables
3. Deploy and verify health: `GET /health → 200`
4. Smoke test each module endpoint with a synthetic payload (no Supabase calls needed at this point)

### Phase 3 — Platform API

1. Create `platform-api` Railway service from GitHub repo (`/platform-api` root)
2. Set all platform-api environment variables including `PIPELINE_API_URL` pointing to the private pipeline-api address
3. Deploy and verify health: `GET /health → 200`
4. Enable Railway private networking between the two services
5. Smoke test: create a client via `POST /clients`, verify website_scrape job enqueues and processes

### Phase 4 — End-to-End Pipeline Test (pre-frontend)

Using a REST client (Postman, Insomnia, or curl):
1. Auth: get a JWT via Supabase Auth REST API
2. Create a client with a real brand guide and website URL
3. POST a run with a real keyword
4. Poll `GET /runs/{run_id}/poll` manually every 10 seconds
5. On completion, `GET /runs/{run_id}` and verify all module outputs are populated and the final article is present

### Phase 5 — Lovable Frontend

1. Create new Lovable project
2. Set environment variables: `VITE_PLATFORM_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
3. Build screens in dependency order:
   - Login screen (no API needed)
   - Client list + client form (needs Phase 3)
   - New run form (needs Phase 3)
   - Run dashboard (needs Phase 3)
   - Run detail + article review (needs Phase 4 complete)
   - Admin: user management, cost dashboard

---

## 13. Logging & Observability

Both services emit structured JSON logs to stdout, which Railway captures and indexes for search. This is the only logging sink in v1. No external observability platform (Datadog, Sentry, etc.) — Railway's built-in log search is sufficient at the team's scale.

### 13.1 Log Format

Use Python's standard `logging` module with a JSON formatter (`python-json-logger`):

```json
{
  "timestamp": "2026-04-30T14:23:01.234Z",
  "level": "INFO",
  "service": "platform-api",
  "request_id": "req_abc123",
  "run_id": "run_xyz789",
  "user_id": "uuid",
  "module": "writer",
  "event": "module_call_complete",
  "duration_ms": 47312,
  "cost_usd": 0.34,
  "message": "Writer module returned successfully"
}
```

Required fields on every log line:
- `timestamp` (ISO 8601, UTC)
- `level` (`DEBUG` / `INFO` / `WARN` / `ERROR`)
- `service` (`platform-api` or `pipeline-api`)
- `event` (machine-readable event identifier — e.g., `run_dispatched`, `module_call_complete`, `schema_version_mismatch`)
- `message` (human-readable)

Optional but heavily used: `request_id`, `run_id`, `user_id`, `client_id`, `module`, `duration_ms`, `cost_usd`.

### 13.2 Correlation IDs

**Request ID:** generated as a FastAPI middleware on every incoming HTTP request (`req_` + 12-char random base32). Attached to `request.state.request_id`, returned in error responses (Section 5.0), and included in every log line emitted during that request.

**Run ID:** the orchestrator binds the `run_id` to the asyncio context so every log emitted during a run carries it. Use `contextvars.ContextVar` to thread the value through `asyncio.gather()` calls without explicit passing.

```python
# pseudocode
run_id_ctx: ContextVar[str] = ContextVar("run_id", default=None)

class RunIdLogFilter(logging.Filter):
    def filter(self, record):
        record.run_id = run_id_ctx.get()
        return True
```

### 13.3 Log Levels by Event Class

| Level | Used for |
|---|---|
| `DEBUG` | Per-LLM-call payloads, full prompt text, full response bodies. **Disabled in production.** Toggle via `LOG_LEVEL` env var when debugging. |
| `INFO` | Stage transitions (`run_dispatched`, `stage_started`, `stage_complete`, `run_complete`), successful module calls, async job claimed/complete, cache hits, client created/edited |
| `WARN` | Module retry attempts, snapshot text truncation (>150,000 chars), SIE degraded-confidence runs (<5 pages), Writer fallback to `1.5-no-context` or `1.5-degraded`, website scrape failures (run continues without it) |
| `ERROR` | Stage failures, schema version mismatches, banned-term leakage aborts, orchestrator unhandled exceptions, Supabase write failures (after retry exhaustion), authentication failures |

### 13.4 Structured Events to Log

The following events should always be logged at the level shown — engineers should not have to decide ad-hoc:

| Event | Level | Service |
|---|---|---|
| `request_received` | INFO | platform-api |
| `request_complete` | INFO | platform-api |
| `auth_failed` | ERROR | platform-api |
| `client_created` / `client_updated` / `client_archived` | INFO | platform-api |
| `file_uploaded` | INFO | platform-api |
| `file_parse_failed` | ERROR | platform-api |
| `run_dispatched` | INFO | platform-api |
| `stage_started` (per module) | INFO | platform-api |
| `stage_complete` (per module) | INFO | platform-api |
| `stage_failed` (per module) | ERROR | platform-api |
| `module_retry_attempt` | WARN | platform-api |
| `schema_version_mismatch` | ERROR | platform-api |
| `concurrency_limit_hit` | WARN | platform-api |
| `run_cancelled` | INFO | platform-api |
| `startup_recovery_run_failed` | WARN | platform-api |
| `async_job_claimed` | INFO | platform-api |
| `async_job_complete` / `async_job_failed` | INFO / ERROR | platform-api |
| `website_scrape_started` / `website_scrape_complete` / `website_scrape_failed` | INFO / INFO / WARN | platform-api |
| `module_invoked` (per call) | INFO | pipeline-api |
| `module_complete` (per call, with duration and cost) | INFO | pipeline-api |
| `module_failed` (per call) | ERROR | pipeline-api |
| `sie_cache_hit` / `sie_cache_miss` | INFO | pipeline-api |
| `llm_call_failed` | ERROR | pipeline-api |
| `external_api_rate_limited` (DataForSEO, ScrapeOwl, etc.) | WARN | pipeline-api |

### 13.5 What NOT to Log

- **Brand guide / ICP raw text.** May contain confidential client positioning. Log only character lengths and parse status, never content.
- **API keys, JWTs, or credentials.** Never log auth headers, even on auth failures — log only that auth failed.
- **Full LLM prompt text in production.** `DEBUG` level only, and `LOG_LEVEL=INFO` in production.
- **Personally identifiable information.** No emails, names, or addresses in log payloads — use user IDs (UUIDs) only.

### 13.6 Searching Logs (Railway)

Common search patterns engineers will use:

| Goal | Search query |
|---|---|
| All logs for one run | `run_id:run_xyz789` |
| All errors today | `level:ERROR` |
| Schema version mismatches | `event:schema_version_mismatch` |
| Slow Writer calls | `module:writer AND duration_ms:>60000` |
| Failed website scrapes | `event:website_scrape_failed` |
| Specific request a user is asking about | `request_id:req_abc123` (paste from error response) |

### 13.7 Future: External Observability

Out of scope for v1 but worth noting: when run volume passes ~100/day, consider adding a structured-log destination like Better Stack, Axiom, or Datadog. The JSON log format above is portable to any of these — no code changes needed beyond a log shipping config.

---

## 14. Open Items (Engineering Decisions Not Yet Made)

These are scoped down from the PRD's "What This PRD Doesn't Cover" — only items that need an engineering decision before coding starts.

| # | Item | Recommendation |
|---|---|---|
| 1 | HTTP client for platform → pipeline calls | Use `httpx` (async-native, cleaner than `aiohttp` for this use case) |
| 2 | Supabase client in FastAPI | Use `supabase-py` v2 with the service role key on the server side |
| 3 | Background task execution for orchestrator | FastAPI `BackgroundTasks` in v1; upgrade to Celery if run volume grows past 200/day |
| 4 | Polling interval | 5 seconds. Revisit if Railway costs become a concern. |
| 5 | File storage path convention | `files/{user_id}/{uuid}/{original_filename}` — namespaced by uploader |
| 6 | Signed URL TTL for file downloads | 60 minutes (Supabase default) |
| 7 | Module output storage | Store full `input_payload` and `output_payload` as jsonb. At ~50 runs/day and ~50KB per run, storage grows at ~2.5MB/day — negligible for the foreseeable future. |
| 8 | Lovable → TanStack Query setup | Initialize in Lovable's main App component; wrap all routes in `QueryClientProvider` |
| 9 | CORS | Platform API allows CORS from Lovable's domain only |
| 10 | Railway service restart policy | Set to "always restart" for both services |
| 11 | JSON log library | `python-json-logger` for both services; configure once at startup |
| 12 | Request ID middleware | Custom FastAPI middleware that generates `req_` + 12-char base32 ID and attaches to `request.state.request_id` |
| 13 | Module schema version registry location | Hardcoded dict in `platform-api/services/orchestrator.py` (Section 6.5); bumped via PR alongside module updates |

---

## 15. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-30 | Initial engineering implementation spec. Covers service topology (2 Railway services), Supabase schema (6 tables + migrations), auth flow, all Platform API routes, orchestration background task pattern, async job worker for website scraping, file parsing, Pipeline API contract, Lovable frontend routes and key components, environment variables, and phased deployment sequence. Based on Platform PRD v1.3 and Writer Module v1.5 Change Spec. |
| 1.1 | 2026-04-30 | Added six review-driven additions: (1) Section 3.4 Storage Buckets — `files` (active) and `article-assets` (placeholder for v2 image generation); (2) Section 5.0 Standard Error Response Format — string-coded errors with `request_id` for log correlation, plus 16-row common error code table; (3) Section 6.5 Module Schema Version Validation — strict-mode registry with no minor-version tolerance, plus three accepted Writer schema versions for fallback paths; (4) Section 9.4 Image References — explicitly out of scope for v1, with the v2 evolution path documented; (5) NewRunForm submit-button debounce documented as the v1 idempotency mechanism (no server-side `Idempotency-Key`); (6) NEW Section 13 Logging & Observability — JSON log format, correlation IDs (request_id and run_id via ContextVar), 25 structured events with mandated log levels, what-not-to-log rules, and Railway log search patterns. Phase 1 deployment sequence updated to use the Supabase CLI workflow with timestamped migration filenames, `supabase link`, `supabase db push`, and local `supabase start` for testing. Open items expanded from 10 to 13 entries covering the new logging/error infrastructure. Version History renumbered from Section 14 to Section 15; Open Items renumbered from 13 to 14. |
