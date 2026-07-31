-- Brand voice & ICP enforcement.
--
-- Every generator already received the client's brand guide and ICP as prose in
-- the prompt, but nothing distilled them into enforceable rules and nothing
-- checked the output against them — so pages scored "good" on the SEO/AEO
-- rubric while failing a human brand-voice audit.
--
-- Two additions:
--   * clients.voice_card — the distilled, enforceable form of brand_voice +
--     detected_icp (tone, grammatical person, must-use / never-use terms, CTA
--     language, the real audience). Cached against a fingerprint of the source
--     documents so distillation is paid once per guide revision rather than
--     once per generated page. Rebuilt lazily on the next generation after the
--     guide changes; nullable, and every consumer treats absent/empty as
--     "no enforcement" and falls back to prior behaviour.
--   * <page>.voice_violations — the deterministic post-generation audit
--     (forbidden terms found, required phrasing missing, grammatical person,
--     CTA language). Stored so the violation survives the generation stream and
--     can be shown next to the content gaps.

alter table public.clients
  add column if not exists voice_card jsonb;

comment on column public.clients.voice_card is
  'Distilled brand voice + ICP card used to steer and check generation. Shape: '
  '{fingerprint, card: {...}, generated_at}. Rebuilt when `fingerprint` no '
  'longer matches a hash of the rendered brand_voice/detected_icp text.';

alter table public.local_seo_pages
  add column if not exists voice_violations jsonb;

comment on column public.local_seo_pages.voice_violations is
  'Deterministic brand-guide audit of the saved page: '
  '{passed, critical_count, warning_count, violations:[{check,severity,message,terms}]}. '
  'Null for pages generated before voice enforcement existed.';

alter table public.ecommerce_pages
  add column if not exists voice_violations jsonb;

comment on column public.ecommerce_pages.voice_violations is
  'Deterministic brand-guide audit of the saved page — same shape as '
  'local_seo_pages.voice_violations.';

-- Pages that break the brand guide are the ones a human needs to look at, and
-- they are a small minority — a partial index keeps that lookup cheap without
-- carrying the whole table.
create index if not exists local_seo_pages_voice_failed_idx
  on public.local_seo_pages (client_id, created_at desc)
  where voice_violations is not null
    and (voice_violations ->> 'passed') = 'false';

create index if not exists ecommerce_pages_voice_failed_idx
  on public.ecommerce_pages (client_id, created_at desc)
  where voice_violations is not null
    and (voice_violations ->> 'passed') = 'false';
