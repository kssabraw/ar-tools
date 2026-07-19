-- Migration: 20260718120000_content_batch_notes_ecommerce.sql
-- Purpose: Standardize the Content Scheduler CSV contract + extend it.
--          (1) Per-row `notes` — free-text writing guidance the user supplies per
--              page (CSV "Notes" column). Fed into generation for every content
--              type (writer_notes for runs, notes for local-SEO/ecommerce), NOT
--              just stored.
--          (2) A 5th content type: 'ecommerce' (product pages), generated via the
--              suite ecommerce writer. Widens both the batches content_type CHECK
--              and the items result_kind CHECK.
--
-- Additive only — existing batches/items are untouched (notes defaults null).

alter table content_batch_items
  add column if not exists notes text;

-- Widen content_batches.content_type to include 'ecommerce'.
alter table content_batches drop constraint if exists content_batches_content_type_check;
alter table content_batches
  add constraint content_batches_content_type_check
  check (content_type in ('blog_post', 'service_page', 'location_page',
                          'local_seo_page', 'ecommerce'));

-- Widen content_batch_items.result_kind to include 'ecommerce_page'.
alter table content_batch_items drop constraint if exists content_batch_items_result_kind_check;
alter table content_batch_items
  add constraint content_batch_items_result_kind_check
  check (result_kind is null or result_kind in ('run', 'local_seo_page', 'ecommerce_page'));
