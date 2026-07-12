-- Brand footprint v1.1 (owner refinement 2026-07-12): the mention metric
-- splits into three distinct signals per competitor —
--   citations          total web mentions (linked AND unlinked — the Content
--                      Analysis index is a content index, not a link index)
--   unlinked_mentions  mentioning domains MINUS linking domains (Content
--                      Analysis search ∖ Backlinks referring-domains)
--   nap_citations      mentions of the business PHONE NUMBER (globally unique
--                      → immune to generic-name inflation; ≈ NAP citations)
-- generic_name flags businesses whose name is category+city+stopword tokens
-- ("Pest Control KC") — their bare-name counts are snippet-filtered by
-- city/phone co-occurrence instead of trusted raw.
alter table public.brand_mentions
  add column if not exists unlinked_mentions bigint,
  add column if not exists nap_citations bigint,
  add column if not exists phone text,
  add column if not exists generic_name boolean not null default false;
