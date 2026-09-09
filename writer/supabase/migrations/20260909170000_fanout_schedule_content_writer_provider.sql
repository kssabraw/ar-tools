-- Fanout content scheduler: which LLM writes the draft prose for this schedule's
-- runs ('anthropic' = Sonnet default | 'openai' = Luna). Null ⇒ default.
alter table fanout.content_schedules
  add column if not exists content_writer_provider text
    check (content_writer_provider is null or content_writer_provider in ('anthropic', 'openai'));
