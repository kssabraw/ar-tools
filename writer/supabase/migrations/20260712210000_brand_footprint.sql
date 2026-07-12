-- LeadOff brand-footprint caches (site size + brand mentions — the two
-- "how big / how branded are the incumbents" ranking-factor context signals).
-- App-owned in public (market_scanner is loader-recreated/grant-stripped).
-- Written by the app's tryout/scout pulls; 90-day pulled_at freshness like
-- the other LeadOff caches. Context only — never a grade input.

-- Google's indexed-page estimate per domain (site:domain se_results_count).
create table if not exists public.domain_site_size (
  domain text primary key,
  indexed_pages bigint,
  pulled_at timestamptz not null default now()
);

-- Web mention footprint per brand (DataForSEO Content Analysis summary).
-- Keyed by the normalized business name GLOBALLY (not per city): a mention
-- count is inherently name-global, and franchises ("Roto-Rooter") then hit
-- cache across every market instead of re-billing per city.
create table if not exists public.brand_mentions (
  brand_key text primary key,
  business_name text,
  citations bigint,
  positive_connotations bigint,
  negative_connotations bigint,
  pulled_at timestamptz not null default now()
);

alter table public.domain_site_size enable row level security;
alter table public.brand_mentions enable row level security;
