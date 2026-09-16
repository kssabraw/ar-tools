-- Migration: 20260916190000_site_claim_index.sql
-- Purpose: Topic-Vector Centering + Information Gain — P1 grounding corpus.
--   See docs/modules/topic-vector-information-gain-plan-v1_0.md §6/§7.
--
--   The per-client SITE CLAIM INDEX: the grounding corpus for the scored
--   Information Gain dimension. A page claim counts as "gain" only when it is
--   (a) on-vector, (b) rare in the top-10, and (c) SITE-GROUNDED — corroborated
--   by a structured fact this client's OWN site actually asserts. Guard (c) is
--   the anti-fabrication mechanism: gain must be SOURCED from the client's site,
--   never generated.
--
--   Cross-service by necessity (§7): site discovery + extraction live in
--   platform-api (services/site_claim_index.py); the scorer that consumes the
--   index lives in nlp-api, which has NO database — so the index is built +
--   cached HERE and passed to nlp in the score/reopt request body, exactly like
--   serp_analysis and researched_facts already are. This table is that cache.
--
--   Keyed on client_id (the corpus is the client's whole site). TTL is a
--   re-crawl cadence, not an expiry; an empty/thin index is never a hard failure
--   — the gain measure SUPPRESSES ("not measured") rather than scoring 0, so a
--   new / sitemap-less client degrades gracefully.
--
-- RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model).

create table if not exists site_claim_index (
  client_id    uuid primary key references clients (id) on delete cascade,
  website_url  text,
  -- Typed structured facts extracted from the client's site (price / purity /
  -- CAS / molecular weight / formula / sequence / storage / sizes / COA /
  -- shipping-returns / …): [{type, value, unit, raw, url}]. Used for the typed
  -- value-agreement grounding path (numerics / prices).
  facts        jsonb   not null default '[]'::jsonb,
  -- Deduped substantive claim phrases from the same pages: [{text, url}].
  -- Embedded on the nlp side (where the Gemini key lives) for the fuzzy
  -- cosine-grounding path — the name-agnostic half (a coded-name claim still
  -- grounds against the coded-name fact on the client's own site).
  claims       jsonb   not null default '[]'::jsonb,
  url_count    integer not null default 0,   -- pages scraped into the index
  source       text    not null default 'none',  -- sitemap | google_index | none
  note         text,                         -- degraded-build reason, if any
  fetched_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table site_claim_index enable row level security;

comment on table site_claim_index is
  'Topic-Vector P1 grounding corpus: per-client structured facts + claim phrases '
  'extracted from the client''s own site, cached in platform-api and passed to '
  'nlp-api in the score/reopt request body (nlp has no DB). Anti-fabrication '
  'ground truth for the scored Information Gain dimension.';
