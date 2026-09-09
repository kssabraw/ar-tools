-- Content-writer model provider (owner request 2026-09).
--
-- A client can standardize on which LLM PROVIDER writes its content drafts, and a
-- single run can override that choice. Only the provider is stored ("anthropic" |
-- "openai"); the concrete OpenAI model id lives in service config
-- (content_writer_openai_model = gpt-5.6-luna), so the Luna version bumps via env
-- with no migration. Applies to all four content writers (blog + service/location
-- in pipeline-api; Local SEO + Ecommerce in nlp-api) via the job/run payloads.
--
-- Effective provider for any piece of content:
--     run/request override  ??  client default  ??  'anthropic'.

-- Per-client default. NOT NULL DEFAULT so every existing + future client reads a
-- concrete value (existing behaviour = 'anthropic' = Claude, unchanged).
alter table public.clients
    add column if not exists content_writer_provider text not null default 'anthropic';

alter table public.clients
    drop constraint if exists clients_content_writer_provider_check;
alter table public.clients
    add constraint clients_content_writer_provider_check
    check (content_writer_provider in ('anthropic', 'openai'));

-- Per-run RESOLVED provider (override ?? client default ?? 'anthropic'), stamped
-- at run creation. Nullable so pre-existing run rows (which predate the column)
-- stay valid and read as "unset" — the orchestrator/writer treat NULL as
-- 'anthropic' (unchanged behaviour).
alter table public.runs
    add column if not exists content_writer_provider text;

alter table public.runs
    drop constraint if exists runs_content_writer_provider_check;
alter table public.runs
    add constraint runs_content_writer_provider_check
    check (content_writer_provider is null or content_writer_provider in ('anthropic', 'openai'));
