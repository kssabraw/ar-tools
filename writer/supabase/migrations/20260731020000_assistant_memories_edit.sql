-- Make assistant memories editable, and make an edit legible.
--
-- Memories are written by the post-turn capture pass and then fed into every
-- future answer about that client. That makes a wrong one quietly durable:
-- there was no way to correct or remove a note, so an error would shape
-- answers indefinitely with no obvious cause. This adds the column the editor
-- needs; the CRUD lives in routers/assistant.py.
--
-- `updated_at` stays NULL until a human touches the note, so the context
-- provider can mark a human-corrected memory as more trustworthy than an
-- auto-captured one.
alter table public.assistant_memories
  add column if not exists updated_at timestamptz;

comment on column public.assistant_memories.updated_at is
  'Set when a human edits the note (NULL = exactly as captured). Lets the assistant weight a corrected memory above an auto-captured one.';
