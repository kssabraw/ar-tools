-- Migration: 20260713000000_ecommerce_pages.sql
-- Purpose: Ecommerce Product & Collection Writer + Reoptimizer module.
--          A per-client store of generated/reoptimized ecommerce pages (product
--          descriptions + collection/category pages), parallel to
--          local_seo_pages. Reuses the same nlp-api generation + auto-retry
--          scoring spine, but with an ecommerce scoring rubric and no geo
--          (national) targeting, so this module drops `location` and adds
--          `page_type` (product|collection) + `source_url` (a live/source page
--          the writer can scrape for facts, and the reoptimize target) +
--          `product_input` (pasted product facts, kept for provenance).
--
--          Two pieces mirror local_seo_page_scores:
--            1. ecommerce_pages.engine_scores — current verdict on the saved row.
--            2. ecommerce_page_scores — per-run scoring history (standalone URL
--               score, generate, reoptimize_before, reoptimize).
--
-- RLS on, service-role only (the backend uses the service-role key and bypasses
-- these; policies gate anon/authenticated access). Mirrors local_seo_pages.

create table ecommerce_pages (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id) on delete cascade,
  -- Target term (product name / collection head term).
  keyword           text not null,
  -- 'product' (a single product description) or 'collection' (a category page).
  page_type         text not null default 'product'
                      check (page_type in ('product', 'collection')),
  -- Optional live/source page: scraped for facts on generate, and the target
  -- of reoptimize-by-URL. Null for a from-scratch paste-only generation.
  source_url        text,
  -- Pasted product facts (specs/features/price/variants) supplied by the user;
  -- stored for provenance (the writer's fact reference).
  product_input     text,
  content_html      text not null default '',
  schema_json       text not null default '',
  page_title        text,
  content_gaps      jsonb not null default '[]'::jsonb,
  composite_score   numeric(5, 2),
  composite_status  text,
  engine_scores     jsonb,
  -- 'generate' (fresh) or 'reoptimize' (rewritten to lift the score).
  mode              text not null default 'generate'
                      check (mode in ('generate', 'reoptimize')),
  token_usage       jsonb,
  cost_breakdown    jsonb,
  -- Publish lifecycle (mirrors local_seo_pages).
  published_doc_id  text,
  published_doc_url text,
  published_url     text,
  published_at      timestamptz,
  featured_image_url text,
  -- Soft-delete → Drafts tab.
  deleted_at        timestamptz,
  created_by        uuid references profiles(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index ecommerce_pages_client_id_idx
  on ecommerce_pages (client_id, created_at desc);
create index idx_ecommerce_pages_client_deleted
  on ecommerce_pages (client_id, deleted_at);

alter table ecommerce_pages enable row level security;

create policy "authenticated users read ecommerce_pages"
  on ecommerce_pages for select
  using (auth.role() = 'authenticated');

create policy "authenticated users create ecommerce_pages"
  on ecommerce_pages for insert
  with check (auth.role() = 'authenticated');

create policy "creators and admins update ecommerce_pages"
  on ecommerce_pages for update
  using (
    created_by = auth.uid()
    or exists (select 1 from profiles where profiles.id = auth.uid() and profiles.role = 'admin')
  );

-- Per-run scoring history (parallel to local_seo_page_scores).
create table ecommerce_page_scores (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  -- Null for a standalone URL score (no page row) or if the page is later deleted.
  page_id          uuid references ecommerce_pages(id) on delete set null,
  keyword          text not null,
  page_type        text,
  page_url         text,
  -- 'score' (standalone) | 'generate' | 'reoptimize' (after) | 'reoptimize_before'
  mode             text not null
                     check (mode in ('score', 'generate', 'reoptimize', 'reoptimize_before')),
  composite_score  numeric,
  composite_status text,
  engine_scores    jsonb,
  deficiencies     jsonb,
  token_usage      jsonb,
  created_by       uuid,
  created_at       timestamptz not null default now()
);

create index idx_ecommerce_page_scores_client_created
  on ecommerce_page_scores (client_id, created_at desc);
create index idx_ecommerce_page_scores_page
  on ecommerce_page_scores (page_id, created_at desc);

alter table ecommerce_page_scores enable row level security;
