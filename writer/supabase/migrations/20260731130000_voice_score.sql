-- Brand voice as a first-class score, not a number buried in an SEO composite.
--
-- The voice verdict already lands in `voice_violations` (jsonb) with its
-- per-dimension breakdown. This lifts the headline number out into its own
-- column so a page's voice score can be sorted, filtered and shown beside its
-- SEO score in list views without unpacking jsonb on every row.
--
-- Nullable throughout: null means the client had no brand guide on file when
-- the page was generated (or the page predates voice scoring), which is a
-- different thing from scoring zero.

alter table public.local_seo_pages
  add column if not exists voice_score numeric;

comment on column public.local_seo_pages.voice_score is
  'Headline brand-voice score 0-100 (weighted across the eight scorecard '
  'dimensions in voice_violations.dimensions). Scored and reported separately '
  'from composite_score, which measures SEO/AEO only. Null = no brand guide on '
  'file for this client at generation time.';

alter table public.ecommerce_pages
  add column if not exists voice_score numeric;

comment on column public.ecommerce_pages.voice_score is
  'Headline brand-voice score 0-100 — same contract as '
  'local_seo_pages.voice_score.';

-- Finding the off-voice pages is the query this exists for. Partial, because
-- pages that pass are the overwhelming majority and are not what anyone looks up.
create index if not exists local_seo_pages_voice_score_idx
  on public.local_seo_pages (client_id, voice_score)
  where voice_score is not null and voice_score < 80;

create index if not exists ecommerce_pages_voice_score_idx
  on public.ecommerce_pages (client_id, voice_score)
  where voice_score is not null and voice_score < 80;
