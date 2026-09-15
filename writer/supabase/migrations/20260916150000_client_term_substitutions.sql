-- Per-client mandatory term substitutions applied to FINAL generated content.
--
-- Some clients must never publish certain words but still want content
-- researched + planned around them (e.g. Nova Life Peptides researches
-- "retatrutide" demand, but every published page must read "glp3-rt" instead —
-- a regulated-compound compliance rule). A brand-voice never-use *ban* only
-- tells the writer to avoid the word; it does not guarantee a specific coded
-- replacement, and on some paths it is not even auto-corrected. This column
-- carries a deterministic {from: to} map that the content generators apply as a
-- word-boundary, case-preserving find/replace on the WRITTEN OUTPUT only
-- (title / body / FAQ / meta / slug) — keyword research, briefs, clustering and
-- SERP analysis deliberately keep the real term.
--
-- Empty map ('{}') is a no-op, so this is inert for every client that has not
-- opted in.

alter table public.clients
  add column if not exists term_substitutions jsonb not null default '{}'::jsonb;

comment on column public.clients.term_substitutions is
  'Deterministic {from: to} map applied to final generated content only (never to keywords/research). Empty = disabled.';
