-- Cache for the ecommerce writer's invariant public-spec research.
--
-- `_research_public_facts` (nlp-api) runs a bounded Anthropic web_search pass to
-- fill the publicly-documented, INVARIANT properties of a product/compound —
-- CAS number, molecular weight/formula, InChI/SMILES, sequence, solubility,
-- reconstitution, storage. On a reference reoptimize it cost $0.372 (31% of the
-- run) and 1m24s of wall clock, and it re-ran from scratch on every reoptimize
-- of the same product. These values never change, so paying for them twice is
-- pure waste.
--
-- The cache is app-owned in `public` and lives HERE rather than in nlp-api
-- because nlp-api has no database at all (no supabase in its requirements, no
-- Supabase env). platform-api looks the facts up, passes them to nlp on the
-- request, and nlp skips its own research when they are supplied; on a miss nlp
-- researches as before and platform stores what comes back.
--
-- Keyed GLOBALLY on a normalized compound name, not per client: a CAS number is
-- a CAS number regardless of who sells the compound, so two clients selling the
-- same peptide share one paid research pass. Mirrors the LeadOff
-- `domain_site_size` / `brand_mentions` caches (same shape, same rationale).
--
-- Freshness is `ecommerce_fact_cache_days` (default 180) — long, because the
-- values are invariant; the TTL is a re-verification cadence, not an expiry.
-- Empty research results are deliberately NOT cached: a compound we found
-- nothing for must re-research later rather than stay permanently gated.

create table if not exists public.ecommerce_public_facts (
  -- Normalized compound key (lowercased, commercial modifiers and dosage/volume
  -- tokens stripped) — see ecommerce_facts_cache.normalize_entity_key.
  entity_key text primary key,
  -- The raw keyword that produced this entry, kept for provenance/debugging.
  entity text not null,
  page_type text not null default 'product',
  -- parse_researched_facts() output: [{field, value, unit, source_name,
  -- source_url, confidence}]. Always non-empty (empties are not cached).
  facts jsonb not null,
  -- The ecommerce_pages row whose generation produced these facts, when known.
  source_page_id uuid,
  fetched_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Freshness sweeps / cache-age reporting.
create index if not exists idx_ecommerce_public_facts_fetched_at
  on public.ecommerce_public_facts (fetched_at);

-- Service-client only, like the other app-owned caches: no policies are defined,
-- so RLS denies everything except the service role (which bypasses it).
alter table public.ecommerce_public_facts enable row level security;
