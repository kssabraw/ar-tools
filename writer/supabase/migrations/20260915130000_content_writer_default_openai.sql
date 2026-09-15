-- Content-writer provider default → OpenAI/Luna (owner request 2026-09-15).
--
-- The agency standardized on OpenAI gpt-5.6-luna for draft prose, so NEW clients
-- should start on it instead of Claude. This flips ONLY the column default (what a
-- client created without an explicit provider gets — e.g. the LeadOff handoff or a
-- SerMaStr-created client); existing client rows are left untouched (the owner set
-- them via the per-client toggle). The post-draft quality gates stay on Claude
-- regardless — this is a draft-prose default only.
--
-- Effective provider for any piece of content is unchanged in shape:
--     run/request override  ??  client default  ??  <code fallback>.
-- The code fallback (services/content_writer.DEFAULT_CONTENT_WRITER_PROVIDER and
-- nlp-api CONTENT_WRITER_PROVIDER_DEFAULT) is moved to 'openai' alongside this so a
-- client row that somehow lacks the column still resolves to Luna.

alter table public.clients
    alter column content_writer_provider set default 'openai';
